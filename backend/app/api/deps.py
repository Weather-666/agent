from collections.abc import Iterator

from fastapi import Depends, Header, Request

from app.clients.acp_gateway import AcpGatewayClient
from app.clients.builder_process import BuilderProcess
from app.clients.gateway_admin import GatewayAdminClient
from app.clients.mcp_gateway import McpGatewayClient
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.core.security import decode_access_token
from app.db import DatabaseConnection, open_database_connection
from app.domain.auth import Principal
from app.services.auth_service import AuthService
from app.services.email_service import EmailService
from app.services.expert_publication_service import ExpertPublicationService
from app.services.mcp_connector_service import McpConnectorService
from app.services.object_store import ObjectStore, create_object_store
from app.services.password_reset_service import PasswordResetService
from app.services.profile_service import ProfileService
from app.services.skill_storage import SkillStorage, create_skill_storage


def get_auth_service(settings: Settings = Depends(get_settings)) -> AuthService:
    return AuthService(settings)


def get_email_service(settings: Settings = Depends(get_settings)) -> EmailService:
    return EmailService(settings)


def get_password_reset_service(
    settings: Settings = Depends(get_settings),
    email_service: EmailService = Depends(get_email_service),
) -> PasswordResetService:
    return PasswordResetService(settings, email_service)


def get_acp_gateway_client(settings: Settings = Depends(get_settings)) -> AcpGatewayClient:
    return AcpGatewayClient(settings)


def get_builder_process(settings: Settings = Depends(get_settings)) -> BuilderProcess:
    return BuilderProcess(settings)


def get_gateway_admin_client(
    settings: Settings = Depends(get_settings),
) -> GatewayAdminClient:
    return GatewayAdminClient(settings)


def get_mcp_gateway_client(settings: Settings = Depends(get_settings)) -> McpGatewayClient:
    return McpGatewayClient(settings)


def get_mcp_connector_service(
    gateway: GatewayAdminClient = Depends(get_gateway_admin_client),
) -> McpConnectorService:
    return McpConnectorService(gateway)


def get_skill_storage(settings: Settings = Depends(get_settings)) -> SkillStorage:
    return create_skill_storage(settings)


def get_object_store(settings: Settings = Depends(get_settings)) -> ObjectStore:
    return create_object_store(settings)


def get_profile_object_store(settings: Settings = Depends(get_settings)) -> ObjectStore:
    try:
        return create_object_store(settings)
    except ApiError as exc:
        if exc.code == "OBJECT_STORE_UNAVAILABLE":
            raise ApiError(
                503,
                "OBJECT_STORE_UNAVAILABLE",
                "Object storage is unavailable",
            ) from exc
        raise


def get_profile_service(
    settings: Settings = Depends(get_settings),
) -> ProfileService:
    return ProfileService(settings)


def get_profile_storage_service(
    settings: Settings = Depends(get_settings),
    object_store: ObjectStore = Depends(get_profile_object_store),
) -> ProfileService:
    return ProfileService(settings, object_store)


def get_database(settings: Settings = Depends(get_settings)) -> Iterator[DatabaseConnection]:
    with open_database_connection(settings) as connection:
        yield connection


def get_expert_publication_service(
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    skill_storage: SkillStorage = Depends(get_skill_storage),
    object_store: ObjectStore = Depends(get_object_store),
    builder: BuilderProcess = Depends(get_builder_process),
    gateway: GatewayAdminClient = Depends(get_gateway_admin_client),
    mcp_gateway: McpGatewayClient = Depends(get_mcp_gateway_client),
    acp: AcpGatewayClient = Depends(get_acp_gateway_client),
) -> ExpertPublicationService:
    return ExpertPublicationService(
        connection,
        settings,
        skill_storage=skill_storage,
        object_store=object_store,
        builder=builder,
        gateway=gateway,
        mcp_gateway=mcp_gateway,
        acp=acp,
    )


def get_request_id(request: Request) -> str:
    return str(request.state.request_id)


async def require_principal(
    authorization: str | None = Header(default=None, alias="Authorization"),
    settings: Settings = Depends(get_settings),
) -> Principal:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "AUTH_UNAUTHORIZED", "Missing bearer token")
    token_principal = decode_access_token(settings, authorization.removeprefix("Bearer ").strip())
    return AuthService(settings).current_principal(token_principal)


async def require_tenant_principal(
    principal: Principal = Depends(require_principal),
    tenant_id: str | None = Header(default=None, alias="x-tenant-id"),
) -> Principal:
    if not tenant_id:
        raise ApiError(401, "AUTH_UNAUTHORIZED", "Missing x-tenant-id")
    if principal.active_tenant_id != tenant_id:
        raise ApiError(403, "AUTH_FORBIDDEN", "Tenant mismatch")
    return principal


async def require_platform_principal(principal: Principal = Depends(require_principal)) -> Principal:
    if not principal.platform_roles:
        raise ApiError(403, "AUTH_FORBIDDEN", "Missing platform role")
    return principal


def require_tenant_permission(permission: str):
    async def dependency(principal: Principal = Depends(require_tenant_principal)) -> Principal:
        if permission not in principal.tenant_permissions:
            raise ApiError(403, "AUTH_FORBIDDEN", f"Missing permission: {permission}")
        return principal

    return dependency


def require_platform_permission(permission: str):
    async def dependency(principal: Principal = Depends(require_platform_principal)) -> Principal:
        if permission not in principal.platform_permissions:
            raise ApiError(403, "AUTH_FORBIDDEN", f"Missing permission: {permission}")
        return principal

    return dependency

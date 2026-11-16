from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.clients.acp_gateway import AcpGatewayClient
from app.clients.builder_process import BuilderProcess
from app.clients.gateway_admin import GatewayAdminClient
from app.clients.mcp_gateway import McpGatewayClient
from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection, open_database_connection
from app.domain.auth import PlatformRole, Principal
from app.services._sql import fetch_one
from app.services.expert_publication_service import ExpertPublicationService
from app.services.expert_repository import ExpertRepository
from app.services.expert_service import ExpertService
from app.services.object_store import create_object_store
from app.services.skill_storage import create_skill_storage


@dataclass(frozen=True)
class ExpertRuntimeReconcileItem:
    expert_id: str
    outcome: Literal["healthy", "repaired", "failed"]
    expert_status: str
    error_code: str | None = None
    fail_closed: bool = True
    fail_closed_error_code: str | None = None


@dataclass(frozen=True)
class ExpertRuntimeReconcileSummary:
    items: tuple[ExpertRuntimeReconcileItem, ...]

    @property
    def healthy(self) -> int:
        return sum(item.outcome == "healthy" for item in self.items)

    @property
    def repaired(self) -> int:
        return sum(item.outcome == "repaired" for item in self.items)

    @property
    def failed(self) -> int:
        return sum(item.outcome == "failed" for item in self.items)


async def reconcile_published_experts(settings: Settings) -> ExpertRuntimeReconcileSummary:
    """Validate published Experts before the API starts accepting traffic.

    Drift uses the normal fail-closed publication lifecycle. A failed repair remains
    unlisted, so marketplace and chat never trust a stale database status alone.
    """
    with open_database_connection(settings) as connection:
        experts = ExpertRepository(connection).list(status="published")
        if not experts:
            return ExpertRuntimeReconcileSummary(items=())

        principal = _platform_admin(connection)
        service = ExpertPublicationService(
            connection,
            settings,
            skill_storage=create_skill_storage(settings),
            object_store=create_object_store(settings),
            builder=BuilderProcess(settings),
            gateway=GatewayAdminClient(settings),
            mcp_gateway=McpGatewayClient(settings),
            acp=AcpGatewayClient(settings),
        )
        items: list[ExpertRuntimeReconcileItem] = []
        for expert in experts:
            try:
                changed = await service.reconcile_published(
                    expert.id,
                    principal=principal,
                    request_id=f"startup-runtime-reconcile-{expert.id}",
                )
                items.append(
                    ExpertRuntimeReconcileItem(
                        expert_id=expert.id,
                        outcome="repaired" if changed else "healthy",
                        expert_status="published",
                    )
                )
            except Exception as error:  # noqa: BLE001 - one Expert must not block others
                current = _fail_closed_status(
                    connection,
                    expert.id,
                    principal,
                    request_id=f"startup-runtime-fail-closed-{expert.id}",
                )
                runtime_fail_closed = True
                fail_closed_error_code: str | None = None
                try:
                    await service.fail_closed_runtime(expert.id)
                except Exception as fail_closed_error:  # noqa: BLE001 - summary gates health
                    runtime_fail_closed = False
                    fail_closed_error_code = (
                        fail_closed_error.code
                        if isinstance(fail_closed_error, ApiError)
                        else type(fail_closed_error).__name__
                    )
                expert_status = current.status if current is not None else "missing"
                items.append(
                    ExpertRuntimeReconcileItem(
                        expert_id=expert.id,
                        outcome="failed",
                        expert_status=expert_status,
                        error_code=(
                            error.code if isinstance(error, ApiError) else type(error).__name__
                        ),
                        fail_closed=expert_status != "published" and runtime_fail_closed,
                        fail_closed_error_code=fail_closed_error_code,
                    )
                )
        return ExpertRuntimeReconcileSummary(items=tuple(items))


def _fail_closed_status(
    connection: DatabaseConnection,
    expert_id: str,
    principal: Principal,
    *,
    request_id: str,
):
    connection.rollback()
    current = ExpertRepository(connection).get(expert_id)
    if current is None or current.status != "published":
        return current
    try:
        return ExpertService(connection).update_status(
            principal,
            expert_id,
            "unlisted",
            request_id=request_id,
        )
    except Exception:  # noqa: BLE001 - lifespan will refuse health if fail-closed also fails
        connection.rollback()
        return ExpertRepository(connection).get(expert_id)


def _platform_admin(connection: DatabaseConnection) -> Principal:
    row = fetch_one(
        connection,
        """
        select u.id, u.email
        from users u
        inner join platform_user_roles r on r.user_id = u.id
        where u.status = 'active' and r.role = 'admin'
        order by u.created_at, u.id
        limit 1
        """,
    )
    if row is None:
        raise RuntimeError(
            "Published Expert reconciliation requires an active platform admin"
        )
    return Principal(
        user_id=str(row["id"]),
        email=str(row["email"]),
        platform_roles=[PlatformRole.ADMIN],
    )

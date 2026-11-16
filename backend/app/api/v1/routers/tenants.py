from fastapi import APIRouter, Depends, Query

from app.api.deps import get_database, get_request_id, require_platform_permission
from app.db import DatabaseConnection
from app.core.config import Settings, get_settings
from app.domain.auth import Principal
from app.domain.plans import BillingPeriod
from app.domain.tenants import (
    AddTenantMemberRequest,
    CreateTenantRequest,
    Tenant,
    TenantFilterOptionsResponse,
    TenantListResponse,
    TenantMember,
    TenantMemberListResponse,
    TenantSubscriptionManagementStatus,
    TenantType,
    UpdateTenantMemberRequest,
    UpdateTenantSubscriptionRequest,
    UpdateTenantRequest,
    UpdateTenantStatusRequest,
)
from app.services.tenant_service import TenantService

router = APIRouter()


@router.get("", response_model=TenantListResponse)
async def list_tenants(
    search: str | None = Query(default=None, min_length=1),
    tenant_type: TenantType | None = Query(default=None, alias="type"),
    subscription_type: BillingPeriod | None = Query(default=None, alias="subscriptionType"),
    subscription_status: TenantSubscriptionManagementStatus | None = Query(
        default=None, alias="subscriptionStatus"
    ),
    sort: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> TenantListResponse:
    items, total = TenantService(connection, settings).list(
        search=search,
        tenant_type=tenant_type,
        subscription_type=subscription_type,
        subscription_status=subscription_status,
        sort=sort,
        page=page,
        page_size=page_size,
    )
    return TenantListResponse(items=items, total=total, page=page, pageSize=page_size)


@router.get("/filter-options", response_model=TenantFilterOptionsResponse)
async def tenant_filter_options(
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
) -> TenantFilterOptionsResponse:
    return TenantService(connection).filter_options()


@router.post("", response_model=Tenant, status_code=201)
async def create_tenant(
    body: CreateTenantRequest,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    request_id: str = Depends(get_request_id),
) -> Tenant:
    return TenantService(connection, settings).create(principal, body, request_id=request_id)


@router.get("/{tenant_id}", response_model=Tenant)
async def get_tenant(
    tenant_id: str,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> Tenant:
    return TenantService(connection, settings).get(tenant_id)


@router.patch("/{tenant_id}", response_model=Tenant)
async def update_tenant(
    tenant_id: str,
    body: UpdateTenantRequest,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    request_id: str = Depends(get_request_id),
) -> Tenant:
    return TenantService(connection, settings).update(
        principal, tenant_id, body, request_id=request_id
    )


@router.patch("/{tenant_id}/status", response_model=Tenant)
async def update_tenant_status(
    tenant_id: str,
    body: UpdateTenantStatusRequest,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    request_id: str = Depends(get_request_id),
) -> Tenant:
    return TenantService(connection, settings).update_status(
        principal, tenant_id, body.status, request_id=request_id
    )


@router.patch(
    "/{tenant_id}/subscription",
    response_model=Tenant,
    responses={409: {"description": "PLAN_CREDIT_ENTITLEMENT_REQUIRED"}},
)
async def update_tenant_subscription(
    tenant_id: str,
    body: UpdateTenantSubscriptionRequest,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    request_id: str = Depends(get_request_id),
) -> Tenant:
    return TenantService(connection, settings).update_subscription(
        principal, tenant_id, body, request_id=request_id
    )


@router.get("/{tenant_id}/members", response_model=TenantMemberListResponse)
async def list_tenant_members(
    tenant_id: str,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
) -> TenantMemberListResponse:
    return TenantMemberListResponse(items=TenantService(connection).list_members(tenant_id))


@router.post("/{tenant_id}/members", response_model=TenantMember, status_code=201)
async def add_tenant_member(
    tenant_id: str,
    body: AddTenantMemberRequest,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> TenantMember:
    return TenantService(connection).add_member(
        principal, tenant_id, body, request_id=request_id
    )


@router.patch("/{tenant_id}/members/{user_id}", response_model=TenantMember)
async def update_tenant_member(
    tenant_id: str,
    user_id: str,
    body: UpdateTenantMemberRequest,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> TenantMember:
    return TenantService(connection).update_member(
        principal, tenant_id, user_id, body, request_id=request_id
    )


@router.delete("/{tenant_id}/members/{user_id}", status_code=204)
async def remove_tenant_member(
    tenant_id: str,
    user_id: str,
    principal: Principal = Depends(require_platform_permission("platform:tenant_manage")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> None:
    TenantService(connection).remove_member(
        principal, tenant_id, user_id, request_id=request_id
    )
    return None

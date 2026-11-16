from fastapi import APIRouter, Depends

from app.api.deps import (
    get_database,
    get_request_id,
    require_principal,
    require_tenant_permission,
)
from app.core.config import Settings, get_settings
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.plans import (
    CurrentSubscriptionResponse,
    PlanListResponse,
    UpgradeSubscriptionRequest,
)
from app.services.plan_service import PlanService
from app.services.subscription_service import SubscriptionService
from app.services.tenant_service import TenantService

router = APIRouter()


@router.get("/plans", response_model=PlanListResponse)
async def list_market_plans(
    principal: Principal = Depends(require_principal),
    connection: DatabaseConnection = Depends(get_database),
) -> PlanListResponse:
    return PlanListResponse(items=PlanService(connection).list_market())


@router.get("/current-subscription", response_model=CurrentSubscriptionResponse)
async def get_current_subscription(
    principal: Principal = Depends(require_principal),
    connection: DatabaseConnection = Depends(get_database),
) -> CurrentSubscriptionResponse:
    return SubscriptionService(connection).current_subscription(principal.active_tenant_id)


@router.patch(
    "/current-subscription",
    response_model=CurrentSubscriptionResponse,
    responses={
        409: {
            "description": (
                "PLAN_NOT_UPGRADE, PLAN_SELF_SERVICE_UNAVAILABLE, or "
                "PLAN_CREDIT_ENTITLEMENT_REQUIRED"
            )
        }
    },
)
async def upgrade_current_subscription(
    body: UpgradeSubscriptionRequest,
    principal: Principal = Depends(require_tenant_permission("tenant:manage")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    request_id: str = Depends(get_request_id),
) -> CurrentSubscriptionResponse:
    return TenantService(connection, settings).upgrade_current_subscription(
        principal,
        str(principal.active_tenant_id),
        body.planId,
        request_id=request_id,
    )

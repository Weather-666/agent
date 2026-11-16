from fastapi import APIRouter, Depends

from app.api.deps import get_database, get_request_id, require_platform_permission
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.plans import (
    CreatePlanRequest,
    Plan,
    PlanListResponse,
    ReplacePlanEntitlementsRequest,
    ReplacePlanExpertsRequest,
    ReplacePlanPricesRequest,
    UpdatePlanRequest,
)
from app.services.plan_service import PlanService

router = APIRouter()


@router.get("", response_model=PlanListResponse)
async def list_plans(
    principal: Principal = Depends(require_platform_permission("plan:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> PlanListResponse:
    return PlanListResponse(items=PlanService(connection).list())


@router.post("", response_model=Plan, status_code=201)
async def create_plan(
    body: CreatePlanRequest,
    principal: Principal = Depends(require_platform_permission("plan:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Plan:
    return PlanService(connection).create(principal, body, request_id=request_id)


@router.get("/{plan_id}", response_model=Plan)
async def get_plan(
    plan_id: str,
    principal: Principal = Depends(require_platform_permission("plan:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> Plan:
    return PlanService(connection).get(plan_id)


@router.patch(
    "/{plan_id}",
    response_model=Plan,
    responses={409: {"description": "CORE_PLAN_CODE_IMMUTABLE or PLAN_CONFLICT"}},
)
async def update_plan(
    plan_id: str,
    body: UpdatePlanRequest,
    principal: Principal = Depends(require_platform_permission("plan:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Plan:
    return PlanService(connection).update(
        principal, plan_id, body, request_id=request_id
    )


@router.put("/{plan_id}/prices", response_model=Plan)
async def replace_plan_prices(
    plan_id: str,
    body: ReplacePlanPricesRequest,
    principal: Principal = Depends(require_platform_permission("plan:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Plan:
    return PlanService(connection).replace_prices(
        principal, plan_id, body, request_id=request_id
    )


@router.put("/{plan_id}/entitlements", response_model=Plan)
async def replace_plan_entitlements(
    plan_id: str,
    body: ReplacePlanEntitlementsRequest,
    principal: Principal = Depends(require_platform_permission("plan:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Plan:
    return PlanService(connection).replace_entitlements(
        principal, plan_id, body, request_id=request_id
    )


@router.put("/{plan_id}/experts", response_model=Plan)
async def replace_plan_experts(
    plan_id: str,
    body: ReplacePlanExpertsRequest,
    principal: Principal = Depends(require_platform_permission("plan:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Plan:
    return PlanService(connection).replace_experts(
        principal, plan_id, body, request_id=request_id
    )


@router.delete(
    "/{plan_id}",
    status_code=204,
    responses={409: {"description": "CORE_PLAN_DELETE_FORBIDDEN or PLAN_HAS_SUBSCRIPTIONS"}},
)
async def delete_plan(
    plan_id: str,
    principal: Principal = Depends(require_platform_permission("plan:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> None:
    PlanService(connection).delete(principal, plan_id, request_id=request_id)
    return None

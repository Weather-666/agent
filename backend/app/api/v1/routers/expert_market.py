from fastapi import APIRouter, Depends, Query

from app.api.deps import get_database, require_principal, require_tenant_principal
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.experts import (
    ExpertMarketCategoryListResponse,
    ExpertMarketExpert,
    ExpertMarketExpertListResponse,
)
from app.services.expert_category_service import ExpertCategoryService
from app.services.expert_service import ExpertService
from app.services.expert_access_service import ExpertAccessService

# The marketplace lists only published experts/categories, but reading it still requires a
# signed-in caller (any authenticated principal) -- it is not an anonymous public endpoint.
router = APIRouter()


@router.get("/categories", response_model=ExpertMarketCategoryListResponse)
async def list_market_categories(
    principal: Principal = Depends(require_principal),
    connection: DatabaseConnection = Depends(get_database),
) -> ExpertMarketCategoryListResponse:
    return ExpertMarketCategoryListResponse(
        items=ExpertCategoryService(connection).list_market_categories()
    )


@router.get(
    "/experts",
    response_model=ExpertMarketExpertListResponse,
    responses={403: {"description": "Tenant context is required"}},
)
async def list_market_experts(
    category_id: str | None = Query(default=None, alias="categoryId", min_length=1),
    principal: Principal = Depends(require_tenant_principal),
    connection: DatabaseConnection = Depends(get_database),
) -> ExpertMarketExpertListResponse:
    access = ExpertAccessService(connection).current_access(str(principal.active_tenant_id))
    items = ExpertService(connection).list_market_experts(category_id=category_id)
    return ExpertMarketExpertListResponse(
        items=[item.model_copy(update={"isAccessible": access.allows(item.id)}) for item in items]
    )


@router.get(
    "/experts/{expert_id}",
    response_model=ExpertMarketExpert,
    responses={403: {"description": "Tenant context is required"}},
)
async def get_market_expert(
    expert_id: str,
    principal: Principal = Depends(require_tenant_principal),
    connection: DatabaseConnection = Depends(get_database),
) -> ExpertMarketExpert:
    item = ExpertService(connection).get_market_expert(expert_id)
    access = ExpertAccessService(connection).current_access(str(principal.active_tenant_id))
    return item.model_copy(update={"isAccessible": access.allows(item.id)})

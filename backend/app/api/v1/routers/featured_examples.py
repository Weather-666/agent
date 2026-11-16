from fastapi import APIRouter, Depends

from app.api.deps import (
    get_database,
    get_request_id,
    require_platform_permission,
    require_tenant_permission,
)
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.featured_examples import (
    CreateFeaturedCategoryRequest,
    CreateFeaturedExampleRequest,
    FeaturedCategory,
    FeaturedCategoryListResponse,
    FeaturedExample,
    FeaturedExampleListResponse,
    FeaturedExampleOrderResponse,
    FeaturedExampleStatus,
    FeaturedExampleUseResponse,
    FeaturedMarketExampleListResponse,
    FeaturedOrderRequest,
    FeaturedReviewState,
    ReviewFeaturedExampleRequest,
    UpdateFeaturedCategoryRequest,
    UpdateFeaturedExampleRequest,
)
from app.services.featured_example_service import FeaturedExampleService

category_router = APIRouter()
router = APIRouter()
market_router = APIRouter()


@category_router.get("", response_model=FeaturedCategoryListResponse)
async def list_categories(
    principal: Principal = Depends(require_platform_permission("featured_example:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> dict:
    return FeaturedExampleService(connection).list_categories()


@category_router.post("", response_model=FeaturedCategory, status_code=201)
async def create_category(
    body: CreateFeaturedCategoryRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).create_category(
        principal, body, request_id=request_id
    )


@category_router.put("/order", response_model=FeaturedCategoryListResponse)
async def order_categories(
    body: FeaturedOrderRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).order_categories(
        principal, body, request_id=request_id
    )


@category_router.patch("/{category_id}", response_model=FeaturedCategory)
async def update_category(
    category_id: str,
    body: UpdateFeaturedCategoryRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).update_category(
        principal, category_id, body, request_id=request_id
    )


@category_router.delete("/{category_id}", status_code=204)
async def delete_category(
    category_id: str,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> None:
    FeaturedExampleService(connection).delete_category(
        principal, category_id, request_id=request_id
    )


@category_router.put("/{category_id}/examples/order", response_model=FeaturedExampleOrderResponse)
async def order_examples(
    category_id: str,
    body: FeaturedOrderRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).order_examples(
        principal, category_id, body, request_id=request_id
    )


@router.get("", response_model=FeaturedExampleListResponse)
async def list_examples(
    categoryId: str | None = None,
    status: FeaturedExampleStatus | None = None,
    reviewState: FeaturedReviewState | None = None,
    keyword: str | None = None,
    principal: Principal = Depends(require_platform_permission("featured_example:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> dict:
    return FeaturedExampleService(connection).list_examples(
        category_id=categoryId, status=status, review_state=reviewState, keyword=keyword
    )


@router.post("", response_model=FeaturedExample, status_code=201)
async def create_example(
    body: CreateFeaturedExampleRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).create_example(
        principal, body, request_id=request_id
    )


@router.get("/{example_id}", response_model=FeaturedExample)
async def get_example(
    example_id: str,
    principal: Principal = Depends(require_platform_permission("featured_example:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> dict:
    return FeaturedExampleService(connection).get_example(example_id)


@router.patch("/{example_id}", response_model=FeaturedExample)
async def update_example(
    example_id: str,
    body: UpdateFeaturedExampleRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).update_example(
        principal, example_id, body, request_id=request_id
    )


@router.delete("/{example_id}", status_code=204)
async def delete_example(
    example_id: str,
    principal: Principal = Depends(require_platform_permission("featured_example:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> None:
    FeaturedExampleService(connection).delete_example(
        principal, example_id, request_id=request_id
    )


@router.post("/{example_id}/review", response_model=FeaturedExample)
async def review_example(
    example_id: str,
    body: ReviewFeaturedExampleRequest,
    principal: Principal = Depends(require_platform_permission("featured_example:publish")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).review_example(
        principal, example_id, body, request_id=request_id
    )


@router.post("/{example_id}/unlist", response_model=FeaturedExample)
async def unlist_example(
    example_id: str,
    principal: Principal = Depends(require_platform_permission("featured_example:publish")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> dict:
    return FeaturedExampleService(connection).unlist_example(
        principal, example_id, request_id=request_id
    )


@market_router.get("/examples", response_model=FeaturedMarketExampleListResponse)
async def list_market(
    categoryId: str | None = None,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    connection: DatabaseConnection = Depends(get_database),
) -> dict:
    return FeaturedExampleService(connection).list_market(category_id=categoryId)


@market_router.post("/examples/{example_id}/use", response_model=FeaturedExampleUseResponse)
async def use_example(
    example_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    connection: DatabaseConnection = Depends(get_database),
) -> dict:
    return FeaturedExampleService(connection).use_example(example_id)

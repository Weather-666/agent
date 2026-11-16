from fastapi import APIRouter, Depends, Query

from app.api.deps import (
    get_database,
    get_expert_publication_service,
    get_request_id,
    require_platform_permission,
)
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.experts import (
    CreateExpertRequest,
    Expert,
    ExpertListResponse,
    ExpertStatsResponse,
    ExpertStatus,
    UpdateExpertRequest,
    UpdateExpertStatusRequest,
)
from app.services.expert_publication_service import ExpertPublicationService
from app.services.expert_service import ExpertService

router = APIRouter()


@router.get("", response_model=ExpertListResponse)
async def list_experts(
    name: str | None = Query(default=None, min_length=1),
    category_id: str | None = Query(default=None, alias="categoryId", min_length=1),
    status: ExpertStatus | None = Query(default=None),
    principal: Principal = Depends(require_platform_permission("expert:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> ExpertListResponse:
    return ExpertListResponse(
        items=ExpertService(connection).list(
            name=name, category_id=category_id, status=status
        )
    )


@router.get("/stats/summary", response_model=ExpertStatsResponse)
async def get_expert_stats(
    principal: Principal = Depends(require_platform_permission("expert:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> ExpertStatsResponse:
    return ExpertService(connection).stats()


@router.post("", response_model=Expert, status_code=201)
async def create_expert(
    body: CreateExpertRequest,
    principal: Principal = Depends(require_platform_permission("expert:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Expert:
    return ExpertService(connection).create(principal, body, request_id=request_id)


@router.get("/{expert_id}", response_model=Expert)
async def get_expert(
    expert_id: str,
    principal: Principal = Depends(require_platform_permission("expert:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> Expert:
    return ExpertService(connection).get(expert_id)


@router.patch("/{expert_id}", response_model=Expert)
async def update_expert(
    expert_id: str,
    body: UpdateExpertRequest,
    principal: Principal = Depends(require_platform_permission("expert:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> Expert:
    return ExpertService(connection).update(principal, expert_id, body, request_id=request_id)


@router.patch("/{expert_id}/status", response_model=Expert)
async def update_expert_status(
    expert_id: str,
    body: UpdateExpertStatusRequest,
    principal: Principal = Depends(require_platform_permission("expert:write")),
    service: ExpertPublicationService = Depends(get_expert_publication_service),
    request_id: str = Depends(get_request_id),
) -> Expert:
    return await service.change_status(
        principal,
        expert_id,
        body.status,
        request_id=request_id,
    )


@router.delete("/{expert_id}", status_code=204)
async def delete_expert(
    expert_id: str,
    principal: Principal = Depends(require_platform_permission("expert:write")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> None:
    ExpertService(connection).delete(principal, expert_id, request_id=request_id)
    return None

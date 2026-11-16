from fastapi import APIRouter, Depends

from app.api.deps import (
    get_database,
    get_request_id,
    get_settings,
    require_platform_permission,
)
from app.core.config import Settings
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.knowledge import ApproveIndexRequest, IndexReview
from app.services.knowledge_index_approval_service import KnowledgeIndexApprovalService


router = APIRouter()


@router.get("/index-review", response_model=IndexReview)
async def get_index_review(
    knowledge_base_id: str,
    principal: Principal = Depends(require_platform_permission("kb:read")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> IndexReview:
    return KnowledgeIndexApprovalService(
        connection, pipeline_version=settings.knowledge_index_pipeline_version
    ).current(principal, knowledge_base_id)


@router.post("/index-review/approve", response_model=IndexReview)
async def approve_index_review(
    knowledge_base_id: str,
    body: ApproveIndexRequest,
    request_id: str = Depends(get_request_id),
    principal: Principal = Depends(require_platform_permission("kb:build")),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> IndexReview:
    return KnowledgeIndexApprovalService(
        connection, pipeline_version=settings.knowledge_index_pipeline_version
    ).approve(
        principal,
        knowledge_base_id,
        body.batchToken,
        request_id=request_id,
    )

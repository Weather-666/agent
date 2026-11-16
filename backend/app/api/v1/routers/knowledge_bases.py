from fastapi import APIRouter, Depends, Query

from app.api.deps import get_database, get_request_id, require_platform_permission
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.knowledge import (
    CreateKnowledgeBaseRequest,
    KnowledgeBase,
    KnowledgeBaseListResponse,
    UpdateKnowledgeBaseRequest,
)
from app.services.knowledge_base_service import KnowledgeBaseService

router = APIRouter()


@router.post("", response_model=KnowledgeBase, status_code=201)
async def create_knowledge_base(
    body: CreateKnowledgeBaseRequest,
    principal: Principal = Depends(require_platform_permission("kb:create")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> KnowledgeBase:
    return KnowledgeBaseService(connection).create(
        principal, body, request_id=request_id
    )


@router.get("", response_model=KnowledgeBaseListResponse)
async def list_knowledge_bases(
    status: str = Query(default="active", pattern="^(active|archived|all)$"),
    principal: Principal = Depends(require_platform_permission("kb:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> KnowledgeBaseListResponse:
    items = KnowledgeBaseService(connection).list(principal, status=status)
    return KnowledgeBaseListResponse(items=items)


@router.get("/{knowledge_base_id}", response_model=KnowledgeBase)
async def get_knowledge_base(
    knowledge_base_id: str,
    principal: Principal = Depends(require_platform_permission("kb:read")),
    connection: DatabaseConnection = Depends(get_database),
) -> KnowledgeBase:
    return KnowledgeBaseService(connection).get(principal, knowledge_base_id)


@router.patch("/{knowledge_base_id}", response_model=KnowledgeBase)
async def update_knowledge_base(
    knowledge_base_id: str,
    body: UpdateKnowledgeBaseRequest,
    principal: Principal = Depends(require_platform_permission("kb:update")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> KnowledgeBase:
    return KnowledgeBaseService(connection).update(
        principal, knowledge_base_id, body, request_id=request_id
    )


@router.post("/{knowledge_base_id}/archive", response_model=KnowledgeBase)
async def archive_knowledge_base(
    knowledge_base_id: str,
    principal: Principal = Depends(require_platform_permission("kb:update")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> KnowledgeBase:
    return KnowledgeBaseService(connection).archive(
        principal, knowledge_base_id, request_id=request_id
    )


@router.post("/{knowledge_base_id}/activate", response_model=KnowledgeBase)
async def activate_knowledge_base(
    knowledge_base_id: str,
    principal: Principal = Depends(require_platform_permission("kb:update")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> KnowledgeBase:
    return KnowledgeBaseService(connection).activate(
        principal, knowledge_base_id, request_id=request_id
    )


@router.delete("/{knowledge_base_id}", status_code=204)
async def delete_knowledge_base(
    knowledge_base_id: str,
    principal: Principal = Depends(require_platform_permission("kb:delete")),
    connection: DatabaseConnection = Depends(get_database),
    request_id: str = Depends(get_request_id),
) -> None:
    KnowledgeBaseService(connection).delete(
        principal, knowledge_base_id, request_id=request_id
    )
    return None

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_database, require_platform_permission
from app.db import DatabaseConnection
from app.domain.audit import (
    AuditCategory,
    AuditEventListResponse,
    AuditOperationType,
)
from app.domain.auth import Principal
from app.services.audit_repository import AuditEventFilters
from app.services.audit_service import AuditService


router = APIRouter()


@router.get("", response_model=AuditEventListResponse)
async def list_audit_events(
    category: AuditCategory | None = Query(default=None),
    operation_type: AuditOperationType | None = Query(default=None, alias="operationType"),
    actor_id: str | None = Query(default=None, alias="actorId", min_length=1, max_length=200),
    resource_type: str | None = Query(default=None, alias="resourceType", min_length=1, max_length=100),
    resource_id: str | None = Query(default=None, alias="resourceId", min_length=1, max_length=200),
    search: str | None = Query(default=None, min_length=1, max_length=200),
    occurred_from: datetime | None = Query(default=None, alias="from"),
    occurred_to: datetime | None = Query(default=None, alias="to"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, alias="pageSize", ge=1, le=100),
    _: Principal = Depends(require_platform_permission("system:audit_read")),
    connection: DatabaseConnection = Depends(get_database),
) -> AuditEventListResponse:
    items, total = AuditService(connection).list(
        AuditEventFilters(
            category=category,
            operation_type=operation_type,
            actor_id=actor_id,
            resource_type=resource_type,
            resource_id=resource_id,
            search=search,
            occurred_from=occurred_from,
            occurred_to=occurred_to,
        ),
        page=page,
        page_size=page_size,
    )
    return AuditEventListResponse(items=items, total=total, page=page, pageSize=page_size)

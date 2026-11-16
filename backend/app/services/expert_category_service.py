from __future__ import annotations

from uuid import uuid4

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.experts import (
    CreateExpertCategoryRequest,
    ExpertCategory,
    ExpertMarketCategory,
    UpdateExpertCategoryRequest,
)
from app.services._sql import is_unique_violation
from app.services.audit_service import AuditService, changes
from app.services.expert_category_repository import ExpertCategoryRepository


class ExpertCategoryService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.repo = ExpertCategoryRepository(connection)

    def list(self) -> list[ExpertCategory]:
        return self.repo.list()

    def list_market_categories(self) -> list[ExpertMarketCategory]:
        return self.repo.list_market()

    def get(self, category_id: str) -> ExpertCategory:
        category = self.repo.get(category_id)
        if not category:
            raise ApiError(404, "EXPERT_CATEGORY_NOT_FOUND", "Expert category not found")
        return category

    def create(
        self,
        principal: Principal,
        request: CreateExpertCategoryRequest,
        *,
        request_id: str,
    ) -> ExpertCategory:
        category_id = f"expert_cat_{uuid4().hex}"
        try:
            self.repo.insert(category_id, request.name, request.description)
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.EXPERT_CATEGORY,
                action="expert_category.create",
                operation_type=AuditOperationType.CREATE,
                resource=AuditResource(
                    type="expert_category", id=category_id, name=request.name
                ),
                metadata={"description": request.description},
            )
            self.connection.commit()
        except Exception as exc:
            if is_unique_violation(exc):
                raise ApiError(
                    409, "EXPERT_CATEGORY_NAME_EXISTS", "Expert category name already exists"
                ) from exc
            raise
        return self.get(category_id)

    def update(
        self,
        principal: Principal,
        category_id: str,
        request: UpdateExpertCategoryRequest,
        *,
        request_id: str,
    ) -> ExpertCategory:
        current = self.get(category_id)
        next_name = request.name if request.name is not None else current.name
        next_description = (
            request.description if request.description is not None else current.description
        )
        event_changes = changes(
            {"name": current.name, "description": current.description},
            {"name": next_name, "description": next_description},
            {"name", "description"},
        )
        try:
            self.repo.update(category_id, next_name, next_description)
            if event_changes:
                audit = AuditService(self.connection)
                audit.record(
                    audit.context(principal, request_id),
                    category=AuditCategory.EXPERT_CATEGORY,
                    action="expert_category.update",
                    operation_type=AuditOperationType.UPDATE,
                    resource=AuditResource(
                        type="expert_category", id=category_id, name=next_name
                    ),
                    changes=event_changes,
                )
            self.connection.commit()
        except Exception as exc:
            if is_unique_violation(exc):
                raise ApiError(
                    409, "EXPERT_CATEGORY_NAME_EXISTS", "Expert category name already exists"
                ) from exc
            raise
        return self.get(category_id)

    def delete(
        self,
        principal: Principal,
        category_id: str,
        *,
        request_id: str,
    ) -> None:
        current = self.get(category_id)
        if self.repo.is_used_by_expert(category_id):
            raise ApiError(
                409,
                "EXPERT_CATEGORY_IN_USE",
                "Expert category is used by one or more experts",
            )
        if self.repo.delete(category_id) <= 0:
            raise ApiError(404, "EXPERT_CATEGORY_NOT_FOUND", "Expert category not found")
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.EXPERT_CATEGORY,
            action="expert_category.delete",
            operation_type=AuditOperationType.DELETE,
            resource=AuditResource(
                type="expert_category", id=current.id, name=current.name
            ),
            metadata={"description": current.description},
        )
        self.connection.commit()

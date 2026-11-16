from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.knowledge import (
    CreateKnowledgeBaseRequest,
    KnowledgeBase,
    UpdateKnowledgeBaseRequest,
)
from app.services.kb_authz import authorize_kb_access
from app.services.audit_service import AuditService, changes
from app.services.knowledge_base_repository import KnowledgeBaseRepository
from app.services.knowledge_index_repository import KnowledgeIndexRepository


class KnowledgeBaseService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection
        self.repo = KnowledgeBaseRepository(connection)

    def create(
        self,
        principal: Principal,
        request: CreateKnowledgeBaseRequest,
        *,
        request_id: str,
    ) -> KnowledgeBase:
        now = _now_iso()
        kb = KnowledgeBase(
            id=f"kb_{uuid4().hex}",
            ownerUserId=principal.user_id,
            name=request.name,
            description=request.description,
            status="active",
            metadata=request.metadata,
            createdAt=now,
            updatedAt=now,
        )
        self.repo.create(kb)
        KnowledgeIndexRepository(self.connection).enqueue_binding_event(
            kb.id, "binding.ensure", now
        )
        created = self.repo.get(kb.id) or kb
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.KNOWLEDGE_BASE,
            action="knowledge_base.create",
            operation_type=AuditOperationType.CREATE,
            resource=AuditResource(type="knowledge_base", id=created.id, name=created.name),
            metadata={"status": created.status},
        )
        self.connection.commit()
        return created

    def get(self, principal: Principal, knowledge_base_id: str) -> KnowledgeBase:
        kb = self.repo.get(knowledge_base_id)
        if not kb:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        authorize_kb_access(principal, kb, "read")
        return kb

    def list(self, principal: Principal, *, status: str = "active") -> list[KnowledgeBase]:
        del principal
        return self.repo.list_for_platform(status=status)

    def update(
        self,
        principal: Principal,
        knowledge_base_id: str,
        request: UpdateKnowledgeBaseRequest,
        *,
        request_id: str,
    ) -> KnowledgeBase:
        kb = self.repo.get(knowledge_base_id)
        if not kb:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        authorize_kb_access(principal, kb, "update")

        updated = self.repo.update(
            knowledge_base_id,
            name=request.name or kb.name,
            description=request.description if request.description is not None else kb.description,
            metadata=request.metadata if request.metadata is not None else kb.metadata,
            updated_at=_now_iso(),
        )
        if not updated:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        event_changes = changes(
            {
                "name": kb.name,
                "description": kb.description,
                "metadataKeys": sorted(kb.metadata),
                "metadataChanged": False,
            },
            {
                "name": updated.name,
                "description": updated.description,
                "metadataKeys": sorted(updated.metadata),
                "metadataChanged": kb.metadata != updated.metadata,
            },
            {"name", "description", "metadataKeys", "metadataChanged"},
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.KNOWLEDGE_BASE,
                action="knowledge_base.update",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(
                    type="knowledge_base", id=updated.id, name=updated.name
                ),
                changes=event_changes,
            )
        self.connection.commit()
        return updated

    def archive(
        self,
        principal: Principal,
        knowledge_base_id: str,
        *,
        request_id: str,
    ) -> KnowledgeBase:
        kb = self.repo.get(knowledge_base_id)
        if not kb:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        # `archive` is a write action, so authorize_kb_access rejects an already-archived base
        # with 409 KB_ARCHIVED -- archiving is not idempotent by design.
        authorize_kb_access(principal, kb, "archive")
        updated = self.repo.set_status(knowledge_base_id, "archived", _now_iso())
        if not updated:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        KnowledgeIndexRepository(self.connection).suspend_knowledge_base_upserts(
            knowledge_base_id, _now_iso()
        )
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.KNOWLEDGE_BASE,
            action="knowledge_base.archive",
            operation_type=AuditOperationType.UPDATE,
            resource=AuditResource(type="knowledge_base", id=kb.id, name=kb.name),
            changes=changes(
                {"status": kb.status}, {"status": updated.status}, {"status"}
            ),
        )
        self.connection.commit()
        return updated

    def activate(
        self,
        principal: Principal,
        knowledge_base_id: str,
        *,
        request_id: str,
    ) -> KnowledgeBase:
        kb = self.repo.get(knowledge_base_id)
        if not kb:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        # `activate` bypasses the archived write-gate -- it is the transition that un-archives a
        # base. Activating an already-active base is a harmless no-op (idempotent).
        authorize_kb_access(principal, kb, "activate")
        updated = self.repo.set_status(knowledge_base_id, "active", _now_iso())
        if not updated:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        event_changes = changes(
            {"status": kb.status}, {"status": updated.status}, {"status"}
        )
        if event_changes:
            audit = AuditService(self.connection)
            audit.record(
                audit.context(principal, request_id),
                category=AuditCategory.KNOWLEDGE_BASE,
                action="knowledge_base.activate",
                operation_type=AuditOperationType.UPDATE,
                resource=AuditResource(type="knowledge_base", id=kb.id, name=kb.name),
                changes=event_changes,
            )
        self.connection.commit()
        return updated

    def delete(
        self,
        principal: Principal,
        knowledge_base_id: str,
        *,
        request_id: str,
    ) -> None:
        kb = self.repo.get(knowledge_base_id)
        if not kb:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        authorize_kb_access(principal, kb, "delete")
        # Soft delete: a hard delete would cascade documents/document_upload_sessions and strand their
        # MinIO objects. The base disappears from all reads immediately; GC
        # (DocumentService.purge_deleted_knowledge_bases) reclaims the objects, then hard-deletes.
        now = _now_iso()
        self.repo.soft_delete(knowledge_base_id, now)
        KnowledgeIndexRepository(self.connection).enqueue_binding_event(
            knowledge_base_id, "binding.delete", now
        )
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.KNOWLEDGE_BASE,
            action="knowledge_base.delete",
            operation_type=AuditOperationType.DELETE,
            resource=AuditResource(type="knowledge_base", id=kb.id, name=kb.name),
            metadata={"status": kb.status},
        )
        self.connection.commit()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

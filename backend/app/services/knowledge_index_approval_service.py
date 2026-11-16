from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.knowledge import IndexReview, IndexReviewDocument
from app.services.audit_service import AuditService
from app.services.kb_authz import authorize_kb_access
from app.services.knowledge_base_repository import KnowledgeBaseRepository
from app.services.knowledge_index_repository import (
    AUTO_INDEX_THRESHOLD_BYTES,
    KnowledgeIndexRepository,
    PendingIndexGeneration,
)


class KnowledgeIndexApprovalService:
    def __init__(self, connection: DatabaseConnection, *, pipeline_version: str) -> None:
        self.connection = connection
        self.pipeline_version = pipeline_version
        self.kbs = KnowledgeBaseRepository(connection)
        self.indexes = KnowledgeIndexRepository(connection)

    def current(self, principal: Principal, knowledge_base_id: str) -> IndexReview:
        self._authorize(principal, knowledge_base_id, "read")
        pending = self.indexes.pending_index_batch(
            knowledge_base_id, pipeline_version=self.pipeline_version
        )
        total = sum(item.file_size_bytes for item in pending)
        if total <= AUTO_INDEX_THRESHOLD_BYTES:
            return self._review(knowledge_base_id, "not_required", [])
        status = (
            "review_required"
            if all(item.parse_status == "ready" for item in pending)
            else "pending_parse"
        )
        return self._review(knowledge_base_id, status, pending)

    def approve(
        self,
        principal: Principal,
        knowledge_base_id: str,
        batch_token: str,
        *,
        request_id: str,
    ) -> IndexReview:
        kb = self._authorize(principal, knowledge_base_id, "build")
        existing = self.indexes.get_approval(knowledge_base_id, batch_token)
        if existing is not None:
            return self._approved(existing)

        review = self.current(principal, knowledge_base_id)
        if review.status != "review_required" or review.batchToken != batch_token:
            raise ApiError(
                409,
                "KB_INDEX_REVIEW_CHANGED",
                "The pending document batch changed; refresh before rebuilding",
                {"knowledgeBaseId": knowledge_base_id},
            )
        pending = self.indexes.pending_index_batch(
            knowledge_base_id, pipeline_version=self.pipeline_version
        )
        now = _now_iso()
        created = self.indexes.create_approval(
            knowledge_base_id,
            batch_token,
            len(pending),
            sum(item.file_size_bytes for item in pending),
            principal.user_id,
            now,
        )
        if not created:
            existing = self.indexes.get_approval(knowledge_base_id, batch_token)
            assert existing is not None
            return self._approved(existing)

        self.indexes.approve_batch(pending, now)
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.KNOWLEDGE_BASE,
            action="knowledge_base.index_approve",
            operation_type=AuditOperationType.UPDATE,
            resource=AuditResource(type="knowledge_base", id=kb.id, name=kb.name),
            metadata={
                "batchToken": batch_token,
                "documentCount": len(pending),
                "totalSizeBytes": sum(item.file_size_bytes for item in pending),
                "thresholdBytes": AUTO_INDEX_THRESHOLD_BYTES,
            },
        )
        self.connection.commit()
        return self._review(knowledge_base_id, "approved", pending, token=batch_token)

    def _authorize(self, principal: Principal, knowledge_base_id: str, action: str):
        kb = self.kbs.get(knowledge_base_id)
        if kb is None:
            raise ApiError(404, "KB_NOT_FOUND", "Knowledge base not found")
        authorize_kb_access(principal, kb, action)
        return kb

    def _review(
        self,
        knowledge_base_id: str,
        status: str,
        documents: list[PendingIndexGeneration],
        *,
        token: str | None = None,
    ) -> IndexReview:
        return IndexReview(
            knowledgeBaseId=knowledge_base_id,
            status=status,
            thresholdBytes=AUTO_INDEX_THRESHOLD_BYTES,
            documentCount=len(documents),
            totalSizeBytes=sum(item.file_size_bytes for item in documents),
            batchToken=token
            or (
                _batch_token(knowledge_base_id, self.pipeline_version, documents)
                if documents
                else None
            ),
            documents=[
                IndexReviewDocument(
                    documentId=item.document_id,
                    fileName=item.file_name,
                    fileSizeBytes=item.file_size_bytes,
                )
                for item in documents
            ],
        )

    def _approved(self, row: dict) -> IndexReview:
        return IndexReview(
            knowledgeBaseId=str(row["knowledge_base_id"]),
            status="approved",
            thresholdBytes=AUTO_INDEX_THRESHOLD_BYTES,
            documentCount=int(row["document_count"]),
            totalSizeBytes=int(row["total_size_bytes"]),
            batchToken=str(row["batch_token"]),
        )


def _batch_token(
    knowledge_base_id: str,
    pipeline_version: str,
    documents: list[PendingIndexGeneration],
) -> str:
    payload = [
        (item.document_id, item.source_sha256, item.file_size_bytes)
        for item in sorted(documents, key=lambda item: (item.document_id, item.source_sha256))
    ]
    raw = json.dumps([knowledge_base_id, pipeline_version, payload], separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

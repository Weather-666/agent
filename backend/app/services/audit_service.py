from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Mapping
from uuid import uuid4

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import (
    AuditActor,
    AuditCategory,
    AuditChange,
    AuditEvent,
    AuditOperationType,
    AuditResource,
    AuditTenant,
)
from app.domain.auth import Principal
from app.services.audit_repository import AuditEventFilters, AuditRepository


@dataclass(frozen=True)
class AuditContext:
    request_id: str
    actor: AuditActor


@dataclass(frozen=True)
class AuditFieldPolicy:
    changes: frozenset[str] = frozenset()
    metadata: frozenset[str] = frozenset()


ACTION_POLICIES: dict[str, AuditFieldPolicy] = {
    "auth.platform_login": AuditFieldPolicy(),
    "platform_user.invite": AuditFieldPolicy(
        metadata=frozenset({"email", "status", "platformRoles"})
    ),
    "user.update": AuditFieldPolicy(changes=frozenset({"name"}), metadata=frozenset({"email"})),
    "user.status_change": AuditFieldPolicy(
        changes=frozenset({"status"}), metadata=frozenset({"email"})
    ),
    "platform_role.grant": AuditFieldPolicy(
        changes=frozenset({"platformRoles"}), metadata=frozenset({"email", "role"})
    ),
    "platform_role.revoke": AuditFieldPolicy(
        changes=frozenset({"platformRoles"}), metadata=frozenset({"email", "role"})
    ),
    "tenant.create": AuditFieldPolicy(metadata=frozenset({"type", "slug", "ownerUserId"})),
    "tenant.update": AuditFieldPolicy(changes=frozenset({"name", "slug", "ownerUserId"})),
    "tenant.status_change": AuditFieldPolicy(changes=frozenset({"status"})),
    "tenant.subscription_change": AuditFieldPolicy(changes=frozenset({"subscription"})),
    "tenant.credit_adjustment": AuditFieldPolicy(
        metadata=frozenset({"amount", "reason", "beneficiaryUserId"})
    ),
    "tenant_member.add": AuditFieldPolicy(metadata=frozenset({"userId", "email", "role"})),
    "tenant_member.role_change": AuditFieldPolicy(
        changes=frozenset({"role"}), metadata=frozenset({"userId", "email"})
    ),
    "tenant_member.remove": AuditFieldPolicy(metadata=frozenset({"userId", "email", "role"})),
    "knowledge_base.create": AuditFieldPolicy(metadata=frozenset({"status"})),
    "knowledge_base.update": AuditFieldPolicy(
        changes=frozenset({"name", "description", "metadataKeys", "metadataChanged"})
    ),
    "knowledge_base.archive": AuditFieldPolicy(changes=frozenset({"status"})),
    "knowledge_base.activate": AuditFieldPolicy(changes=frozenset({"status"})),
    "knowledge_base.delete": AuditFieldPolicy(metadata=frozenset({"status"})),
    "knowledge_base.build": AuditFieldPolicy(
        metadata=frozenset({"knowledgeBaseId", "knowledgeBaseName", "documentCount"})
    ),
    "knowledge_base.build.cancel": AuditFieldPolicy(metadata=frozenset({"knowledgeBaseId"})),
    "knowledge_base.index_approve": AuditFieldPolicy(
        metadata=frozenset({"batchToken", "documentCount", "totalSizeBytes", "thresholdBytes"})
    ),
    "document.upload_completed": AuditFieldPolicy(
        metadata=frozenset(
            {
                "fileName",
                "fileType",
                "mimeType",
                "fileSizeBytes",
                "knowledgeBaseId",
                "knowledgeBaseName",
            }
        )
    ),
    "document.source_replaced": AuditFieldPolicy(
        metadata=frozenset(
            {
                "fileName",
                "fileType",
                "mimeType",
                "fileSizeBytes",
                "knowledgeBaseId",
                "knowledgeBaseName",
                "previousSourceSha",
                "sourceSha",
            }
        )
    ),
    "document.update": AuditFieldPolicy(
        changes=frozenset({"fileName", "metadataKeys", "metadataChanged"}),
        metadata=frozenset({"mimeType", "fileSizeBytes", "knowledgeBaseId", "knowledgeBaseName"}),
    ),
    "document.delete": AuditFieldPolicy(
        metadata=frozenset(
            {
                "fileName",
                "fileType",
                "mimeType",
                "fileSizeBytes",
                "knowledgeBaseId",
                "knowledgeBaseName",
            }
        )
    ),
    "skill.create": AuditFieldPolicy(
        metadata=frozenset({"slug", "version", "allowedTools", "tags", "fileCount"})
    ),
    "skill.update": AuditFieldPolicy(
        changes=frozenset({"name", "description", "version", "allowedTools", "tags"})
    ),
    "skill.delete": AuditFieldPolicy(
        metadata=frozenset({"slug", "version", "fileCount", "deleteFiles"})
    ),
    "featured_category.create": AuditFieldPolicy(metadata=frozenset({"tone"})),
    "featured_category.update": AuditFieldPolicy(changes=frozenset({"name", "tone"})),
    "featured_category.delete": AuditFieldPolicy(),
    "featured_category.reorder": AuditFieldPolicy(metadata=frozenset({"ids"})),
    "featured_example.create": AuditFieldPolicy(
        metadata=frozenset({"categoryId", "reviewCycleDays"})
    ),
    "featured_example.update": AuditFieldPolicy(
        changes=frozenset({"categoryId", "reviewCycleDays", "status"}),
        metadata=frozenset({"questionChanged"}),
    ),
    "featured_example.delete": AuditFieldPolicy(metadata=frozenset({"categoryId", "status"})),
    "featured_example.reorder": AuditFieldPolicy(metadata=frozenset({"ids", "categoryId"})),
    "featured_example.review": AuditFieldPolicy(
        changes=frozenset({"status"}),
        metadata=frozenset({"decision", "reviewCycleDays"}),
    ),
    "featured_example.unlist": AuditFieldPolicy(changes=frozenset({"status"})),
    "expert_category.create": AuditFieldPolicy(metadata=frozenset({"description"})),
    "expert_category.update": AuditFieldPolicy(changes=frozenset({"name", "description"})),
    "expert_category.delete": AuditFieldPolicy(metadata=frozenset({"description"})),
    "expert.create": AuditFieldPolicy(
        metadata=frozenset(
            {
                "categoryId",
                "status",
                "skillIds",
                "knowledgeBaseIds",
                "tags",
                "marketLabels",
                "runtimeTypes",
            }
        )
    ),
    "expert.update": AuditFieldPolicy(
        changes=frozenset(
            {
                "name",
                "categoryId",
                "abilityIntro",
                "localizedContent",
                "tags",
                "marketLabels",
                "skillIds",
                "knowledgeBaseIds",
                "guideQuestions",
                "summonButtonText",
                "instructions",
                "runtimeConfig",
                "mcpConnectorIds",
                "skillRuntimeTargets",
            }
        )
    ),
    "expert.status_change": AuditFieldPolicy(changes=frozenset({"status"})),
    "expert.delete": AuditFieldPolicy(
        metadata=frozenset({"categoryId", "status", "skillIds", "knowledgeBaseIds"})
    ),
    "plan.create": AuditFieldPolicy(metadata=frozenset({"code", "level", "status"})),
    "plan.update": AuditFieldPolicy(
        changes=frozenset(
            {
                "code",
                "name",
                "level",
                "description",
                "typeLabel",
                "subtitle",
                "badgeLabel",
                "highlightItems",
                "localizedContent",
                "upgradeRuleKeys",
                "upgradeRulesChanged",
                "status",
                "isRecommended",
                "sortOrder",
            }
        )
    ),
    "plan.prices_replace": AuditFieldPolicy(changes=frozenset({"prices"})),
    "plan.entitlements_replace": AuditFieldPolicy(changes=frozenset({"entitlements"})),
    "plan.experts_replace": AuditFieldPolicy(changes=frozenset({"expertIds"})),
    "plan.delete": AuditFieldPolicy(metadata=frozenset({"code", "level", "status"})),
    "library.upload_completed": AuditFieldPolicy(
        metadata=frozenset({"spaceType", "fileName", "mimeType", "fileSizeBytes"})
    ),
    "library.content_read": AuditFieldPolicy(
        metadata=frozenset({"spaceType", "fileName", "mimeType", "fileSizeBytes", "disposition"})
    ),
    "library.agent_content_read": AuditFieldPolicy(
        metadata=frozenset({
            "spaceType", "fileName", "mimeType", "fileSizeBytes", "turnId", "offset", "endOffset"
        })
    ),
    "library.agent_delivery_consumed": AuditFieldPolicy(
        metadata=frozenset({"spaceType", "fileName", "mimeType", "fileSizeBytes", "turnId"})
    ),
    "library.rename": AuditFieldPolicy(changes=frozenset({"name"})),
    "library.delete": AuditFieldPolicy(
        metadata=frozenset({"spaceType", "fileName", "mimeType", "fileSizeBytes", "readOnlyAdmin"})
    ),
}


class AuditService:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.repo = AuditRepository(connection)

    def context(self, principal: Principal, request_id: str) -> AuditContext:
        row = self.repo.actor(principal.user_id)
        if not row:
            raise ApiError(401, "AUTH_USER_DISABLED", "User not found or disabled")
        return AuditContext(
            request_id=request_id,
            actor=AuditActor(
                userId=principal.user_id,
                name=str(row["name"]),
                email=str(row["email"]),
                platformRoles=sorted(role.value for role in principal.platform_roles),
            ),
        )

    def record(
        self,
        context: AuditContext,
        *,
        category: AuditCategory,
        action: str,
        operation_type: AuditOperationType,
        resource: AuditResource,
        changes: Mapping[str, AuditChange] | None = None,
        metadata: Mapping[str, Any] | None = None,
        tenant: AuditTenant | None = None,
    ) -> AuditEvent:
        safe_changes = dict(changes or {})
        safe_metadata = dict(metadata or {})
        _validate_fields(action, safe_changes, safe_metadata)
        event = AuditEvent(
            id=f"audit_{uuid4().hex}",
            requestId=context.request_id,
            occurredAt=datetime.now(timezone.utc).isoformat(),
            category=category,
            action=action,
            operationType=operation_type,
            actor=context.actor,
            tenant=tenant,
            resource=resource,
            changes=safe_changes,
            metadata=safe_metadata,
            clientIp=None,
        )
        self.repo.insert(event)
        return event

    def list(
        self,
        filters: AuditEventFilters,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditEvent], int]:
        filters = replace(
            filters,
            occurred_from=_utc_datetime(filters.occurred_from),
            occurred_to=_utc_datetime(filters.occurred_to),
        )
        if (
            filters.occurred_from is not None
            and filters.occurred_to is not None
            and filters.occurred_from > filters.occurred_to
        ):
            raise ApiError(400, "AUDIT_TIME_RANGE_INVALID", "from must not be later than to")
        return self.repo.list(filters, page=page, page_size=page_size)


def changes(
    before: Mapping[str, Any],
    after: Mapping[str, Any],
    fields: set[str] | frozenset[str],
) -> dict[str, AuditChange]:
    return {
        field: AuditChange(before=before.get(field), after=after.get(field))
        for field in fields
        if before.get(field) != after.get(field)
    }


def _validate_fields(
    action: str,
    event_changes: Mapping[str, AuditChange],
    metadata: Mapping[str, Any],
) -> None:
    policy = ACTION_POLICIES.get(action)
    if policy is None:
        raise ValueError(f"Unsupported audit action: {action}")
    extra_changes = set(event_changes) - policy.changes
    extra_metadata = set(metadata) - policy.metadata
    if extra_changes or extra_metadata:
        raise ValueError(
            f"Audit action {action} received non-whitelisted fields: "
            f"changes={sorted(extra_changes)}, metadata={sorted(extra_metadata)}"
        )


def _utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

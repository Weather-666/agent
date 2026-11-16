from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AuditCategory(StrEnum):
    AUTH = "auth"
    PLATFORM_USER = "platform_user"
    USER = "user"
    PLATFORM_ROLE = "platform_role"
    TENANT = "tenant"
    TENANT_MEMBER = "tenant_member"
    KNOWLEDGE_BASE = "knowledge_base"
    DOCUMENT = "document"
    SKILL = "skill"
    EXPERT_CATEGORY = "expert_category"
    EXPERT = "expert"
    FEATURED_EXAMPLE = "featured_example"
    PLAN = "plan"
    LIBRARY = "library"


class AuditOperationType(StrEnum):
    CREATE = "create"
    READ = "read"
    UPDATE = "update"
    DELETE = "delete"
    LOGIN = "login"
    GRANT = "grant"
    REVOKE = "revoke"
    UPLOAD = "upload"


class AuditActor(BaseModel):
    userId: str
    name: str
    email: str
    platformRoles: list[str] = Field(default_factory=list)


class AuditTenant(BaseModel):
    id: str
    name: str


class AuditResource(BaseModel):
    type: str
    id: str
    name: str | None = None


class AuditChange(BaseModel):
    before: Any = None
    after: Any = None


class AuditEvent(BaseModel):
    id: str
    requestId: str
    occurredAt: str
    category: AuditCategory
    action: str
    operationType: AuditOperationType
    actor: AuditActor
    tenant: AuditTenant | None = None
    resource: AuditResource
    changes: dict[str, AuditChange] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    clientIp: None = None


class AuditEventListResponse(BaseModel):
    items: list[AuditEvent]
    total: int
    page: int
    pageSize: int

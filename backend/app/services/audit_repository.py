from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
from app.services._sql import execute, fetch_all, fetch_one, json_load, json_load_list, json_param


@dataclass(frozen=True)
class AuditEventFilters:
    category: AuditCategory | None = None
    operation_type: AuditOperationType | None = None
    actor_id: str | None = None
    resource_type: str | None = None
    resource_id: str | None = None
    search: str | None = None
    occurred_from: datetime | None = None
    occurred_to: datetime | None = None


class AuditRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def actor(self, user_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            "select id, name, email from users where id = ? limit 1",
            (user_id,),
        )

    def insert(self, event: AuditEvent) -> None:
        execute(
            self.connection,
            """
            insert into audit_events (
              id, request_id, occurred_at, category, action, operation_type,
              actor_user_id, actor_name, actor_email, actor_platform_roles,
              tenant_id, tenant_name, resource_type, resource_id, resource_name,
              changes, metadata, client_ip
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.id,
                event.requestId,
                event.occurredAt,
                event.category.value,
                event.action,
                event.operationType.value,
                event.actor.userId,
                event.actor.name,
                event.actor.email,
                json_param(self.connection, event.actor.platformRoles),
                event.tenant.id if event.tenant else None,
                event.tenant.name if event.tenant else None,
                event.resource.type,
                event.resource.id,
                event.resource.name,
                json_param(
                    self.connection,
                    {key: value.model_dump(mode="json") for key, value in event.changes.items()},
                ),
                json_param(self.connection, event.metadata),
                None,
            ),
        )

    def list(
        self,
        filters: AuditEventFilters,
        *,
        page: int,
        page_size: int,
    ) -> tuple[list[AuditEvent], int]:
        where, params = _where(filters)
        total_row = fetch_one(
            self.connection,
            f"select count(*) as count from audit_events {where}",
            params,
        )
        rows = fetch_all(
            self.connection,
            f"""
            select
              id, request_id, occurred_at, category, action, operation_type,
              actor_user_id, actor_name, actor_email, actor_platform_roles,
              tenant_id, tenant_name, resource_type, resource_id, resource_name,
              changes, metadata, client_ip
            from audit_events
            {where}
            order by occurred_at desc, id desc
            limit ? offset ?
            """,
            (*params, page_size, (page - 1) * page_size),
        )
        return [_map_event(row) for row in rows], int(total_row["count"] if total_row else 0)


def _where(filters: AuditEventFilters) -> tuple[str, tuple[Any, ...]]:
    clauses: list[str] = []
    params: list[Any] = []
    if filters.category is not None:
        clauses.append("category = ?")
        params.append(filters.category.value)
    if filters.operation_type is not None:
        clauses.append("operation_type = ?")
        params.append(filters.operation_type.value)
    if filters.actor_id:
        clauses.append("actor_user_id = ?")
        params.append(filters.actor_id)
    if filters.resource_type:
        clauses.append("resource_type = ?")
        params.append(filters.resource_type)
    if filters.resource_id:
        clauses.append("resource_id = ?")
        params.append(filters.resource_id)
    if filters.search:
        clauses.append(
            "(" 
            "lower(actor_name) like ? escape '\\' or "
            "lower(actor_email) like ? escape '\\' or "
            "lower(coalesce(resource_name, '')) like ? escape '\\' or "
            "lower(resource_id) like ? escape '\\' or "
            "lower(action) like ? escape '\\'"
            ")"
        )
        needle = f"%{_escape_like(filters.search.casefold())}%"
        params.extend([needle] * 5)
    if filters.occurred_from is not None:
        clauses.append("occurred_at >= ?")
        params.append(filters.occurred_from.isoformat())
    if filters.occurred_to is not None:
        clauses.append("occurred_at <= ?")
        params.append(filters.occurred_to.isoformat())
    return (f"where {' and '.join(clauses)}" if clauses else "", tuple(params))


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _map_event(row: dict[str, Any]) -> AuditEvent:
    raw_changes = json_load(row["changes"])
    return AuditEvent(
        id=str(row["id"]),
        requestId=str(row["request_id"]),
        occurredAt=str(row["occurred_at"]),
        category=AuditCategory(str(row["category"])),
        action=str(row["action"]),
        operationType=AuditOperationType(str(row["operation_type"])),
        actor=AuditActor(
            userId=str(row["actor_user_id"]),
            name=str(row["actor_name"]),
            email=str(row["actor_email"]),
            platformRoles=json_load_list(row["actor_platform_roles"]),
        ),
        tenant=(
            AuditTenant(id=str(row["tenant_id"]), name=str(row["tenant_name"]))
            if row["tenant_id"] is not None and row["tenant_name"] is not None
            else None
        ),
        resource=AuditResource(
            type=str(row["resource_type"]),
            id=str(row["resource_id"]),
            name=str(row["resource_name"]) if row["resource_name"] is not None else None,
        ),
        changes={key: AuditChange.model_validate(value) for key, value in raw_changes.items()},
        metadata=json_load(row["metadata"]),
        clientIp=None,
    )


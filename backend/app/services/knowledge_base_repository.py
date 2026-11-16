from __future__ import annotations

from typing import Any

from app.db import DatabaseConnection
from app.domain.knowledge import KnowledgeBase
from app.services._sql import execute, fetch_all, fetch_one, json_load, json_param, rowcount


_INSERT_COLUMNS = (
    "id, owner_user_id, name, description, status, index_status, index_error, metadata, "
    "created_at, updated_at"
)
_SELECT_COLUMNS = (
    "kb.id, kb.owner_user_id, u.name as owner_user_name, kb.name, kb.description, "
    "kb.status, kb.index_status, kb.index_error, "
    "(select li.workspace from knowledge_base_lightrag_instances li "
    " where li.knowledge_base_id = kb.id limit 1) as index_workspace, "
    "kb.metadata, kb.created_at, kb.updated_at"
)


class KnowledgeBaseRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def create(self, kb: KnowledgeBase) -> KnowledgeBase:
        execute(
            self.connection,
            f"""
            insert into knowledge_bases ({_INSERT_COLUMNS})
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                kb.id,
                kb.ownerUserId,
                kb.name,
                kb.description,
                kb.status,
                kb.indexStatus,
                kb.indexError,
                json_param(self.connection, kb.metadata),
                kb.createdAt,
                kb.updatedAt,
            ),
        )
        return kb

    def get(self, knowledge_base_id: str) -> KnowledgeBase | None:
        row = fetch_one(
            self.connection,
            f"""
            select {_SELECT_COLUMNS}
            from knowledge_bases kb
            left join users u on u.id = kb.owner_user_id
            where kb.id = ? and kb.deleted_at is null
            limit 1
            """,
            (knowledge_base_id,),
        )
        return _map_kb(row)

    def update(
        self,
        knowledge_base_id: str,
        *,
        name: str,
        description: str | None,
        metadata: dict[str, Any],
        updated_at: str,
    ) -> KnowledgeBase | None:
        execute(
            self.connection,
            """
            update knowledge_bases
            set name = ?, description = ?, metadata = ?, updated_at = ?
            where id = ?
            """,
            (
                name,
                description,
                json_param(self.connection, metadata),
                updated_at,
                knowledge_base_id,
            ),
        )
        return self.get(knowledge_base_id)

    def set_status(
        self, knowledge_base_id: str, status: str, updated_at: str
    ) -> KnowledgeBase | None:
        execute(
            self.connection,
            """
            update knowledge_bases
            set status = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (status, updated_at, knowledge_base_id),
        )
        return self.get(knowledge_base_id)

    def soft_delete(self, knowledge_base_id: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update knowledge_bases
            set deleted_at = ?, index_status = 'deleting', index_error = null, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (now, now, knowledge_base_id),
        )
        return rowcount(cursor) > 0

    def set_index_state(
        self,
        knowledge_base_id: str,
        status: str,
        *,
        error: str | None,
        updated_at: str,
    ) -> None:
        execute(
            self.connection,
            """
            update knowledge_bases
            set index_status = ?, index_error = ?, updated_at = ?
            where id = ?
            """,
            (status, error, updated_at, knowledge_base_id),
        )

    def list_index_lifecycle_rows(self, limit: int) -> list[dict[str, Any]]:
        """Source-of-truth rows used to recreate lost outbox events on startup."""
        return fetch_all(
            self.connection,
            """
            select kb.id, kb.deleted_at, kb.index_status,
                   li.base_url, li.workspace, li.status as binding_status
            from knowledge_bases kb
            left join knowledge_base_lightrag_instances li
              on li.knowledge_base_id = kb.id
            order by kb.created_at asc, kb.id asc
            limit ?
            """,
            (limit,),
        )

    def list_live_index_ids(self) -> list[str]:
        rows = fetch_all(
            self.connection,
            """
            select id from knowledge_bases
            where deleted_at is null
            order by created_at asc, id asc
            """,
        )
        return [str(row["id"]) for row in rows]

    def delete(self, knowledge_base_id: str) -> None:
        """Hard delete. Used only by GC after the objects have been reclaimed -- the API delete
        path is a soft delete (see soft_delete)."""
        execute(
            self.connection,
            "delete from knowledge_bases where id = ?",
            (knowledge_base_id,),
        )

    def list_soft_deleted(self, limit: int) -> list[str]:
        rows = fetch_all(
            self.connection,
            """
            select id from knowledge_bases
            where deleted_at is not null
            order by deleted_at asc
            limit ?
            """,
            (limit,),
        )
        return [str(row["id"]) for row in rows]

    def list_for_platform(self, *, status: str = "active") -> list[KnowledgeBase]:
        if status not in {"active", "archived", "all"}:
            raise ValueError("Unsupported knowledge-base status filter")
        status_filter = "" if status == "all" else "and kb.status = ?"
        params = () if status == "all" else (status,)
        rows = fetch_all(
            self.connection,
            f"""
            select {_SELECT_COLUMNS}
            from knowledge_bases kb
            left join users u on u.id = kb.owner_user_id
            where kb.deleted_at is null {status_filter}
            order by kb.created_at desc, kb.id asc
            """,
            params,
        )
        return [kb for kb in (_map_kb(row) for row in rows) if kb is not None]


def _map_kb(row: dict[str, Any] | None) -> KnowledgeBase | None:
    if not row:
        return None
    return KnowledgeBase(
        id=str(row["id"]),
        ownerUserId=str(row["owner_user_id"]) if row["owner_user_id"] is not None else None,
        ownerUserName=(
            str(row["owner_user_name"]) if row.get("owner_user_name") is not None else None
        ),
        name=str(row["name"]),
        description=str(row["description"]) if row["description"] is not None else None,
        status=str(row["status"]),
        indexStatus=str(row.get("index_status") or "provisioning"),
        indexError=str(row["index_error"]) if row.get("index_error") is not None else None,
        indexWorkspace=(
            str(row["index_workspace"]) if row.get("index_workspace") is not None else None
        ),
        metadata=json_load(row["metadata"]),
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )

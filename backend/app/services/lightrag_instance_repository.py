from __future__ import annotations

from dataclasses import dataclass

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.services._sql import execute, fetch_all, fetch_one


@dataclass(frozen=True)
class LightragBinding:
    knowledge_base_id: str
    base_url: str
    workspace: str
    provider: str
    provider_ref: str | None = None
    status: str = "ready"
    last_error: str | None = None


class LightragInstanceRepository:
    """Persistent identities for Controller-provisioned per-KB LightRAG instances."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def bindings(self) -> list[LightragBinding]:
        rows = fetch_all(
            self.connection,
            """
            select knowledge_base_id, base_url, workspace, provider, provider_ref,
                   status, last_error
            from knowledge_base_lightrag_instances
            where workspace is not null and provider is not null
              and provider_ref is not null
              and (status = 'ready' or status is null)
            order by created_at asc, knowledge_base_id asc
            """,
        )
        return [_binding_from_row(row) for row in rows]

    def map(self) -> dict[str, str]:
        """Return the fail-closed KB-to-endpoint view used by retrieval callers."""
        return {binding.knowledge_base_id: binding.base_url for binding in self.bindings()}

    def get_binding(self, knowledge_base_id: str) -> LightragBinding | None:
        row = fetch_one(
            self.connection,
            """
            select knowledge_base_id, base_url, workspace, provider, provider_ref,
                   status, last_error
            from knowledge_base_lightrag_instances
            where knowledge_base_id = ? and workspace is not null
              and provider is not null and provider_ref is not null
            limit 1
            """,
            (knowledge_base_id,),
        )
        return _binding_from_row(row) if row else None

    def require_binding(self, knowledge_base_id: str) -> LightragBinding:
        binding = self.get_binding(knowledge_base_id)
        if binding is None or binding.status != "ready":
            raise ApiError(
                503,
                "LIGHTRAG_INSTANCE_NOT_ASSIGNED",
                "Knowledge base has no isolated LightRAG instance",
                {"knowledgeBaseId": knowledge_base_id},
            )
        return binding

    def upsert_ready(
        self,
        knowledge_base_id: str,
        *,
        provider: str,
        provider_ref: str,
        base_url: str,
        workspace: str,
        now: str,
    ) -> LightragBinding:
        """Persist an idempotently ensured dynamic instance without sharing any identity."""
        execute(
            self.connection,
            """
            insert into knowledge_base_lightrag_instances (
              knowledge_base_id, base_url, workspace, provider, provider_ref,
              status, last_error, retry_count, last_healthy_at, created_at, updated_at
            ) values (?, ?, ?, ?, ?, 'ready', null, 0, ?, ?, ?)
            on conflict (knowledge_base_id) do update set
              base_url = excluded.base_url,
              workspace = excluded.workspace,
              provider = excluded.provider,
              provider_ref = excluded.provider_ref,
              status = 'ready',
              last_error = null,
              retry_count = 0,
              last_healthy_at = excluded.last_healthy_at,
              updated_at = excluded.updated_at
            """,
            (
                knowledge_base_id,
                base_url,
                workspace,
                provider,
                provider_ref,
                now,
                now,
                now,
            ),
        )
        binding = self.get_binding(knowledge_base_id)
        assert binding is not None
        return binding

    def mark_ready(self, knowledge_base_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_base_lightrag_instances
            set status = 'ready', last_error = null, retry_count = 0,
                last_healthy_at = ?, updated_at = ?
            where knowledge_base_id = ?
            """,
            (now, now, knowledge_base_id),
        )

    def mark_failed(self, knowledge_base_id: str, error: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_base_lightrag_instances
            set status = 'failed', last_error = ?, retry_count = retry_count + 1,
                updated_at = ?
            where knowledge_base_id = ?
            """,
            (error[:4000], now, knowledge_base_id),
        )

    def remove(self, knowledge_base_id: str) -> None:
        execute(
            self.connection,
            "delete from knowledge_base_lightrag_instances where knowledge_base_id = ?",
            (knowledge_base_id,),
        )

def _binding_from_row(row) -> LightragBinding:
    return LightragBinding(
        knowledge_base_id=str(row["knowledge_base_id"]),
        base_url=str(row["base_url"]),
        workspace=str(row["workspace"]),
        provider=str(row.get("provider") or ""),
        provider_ref=(
            str(row["provider_ref"]) if row.get("provider_ref") is not None else None
        ),
        status=str(row.get("status") or "ready"),
        last_error=str(row["last_error"]) if row.get("last_error") is not None else None,
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.db import DatabaseConnection
from app.services._sql import execute, fetch_all, fetch_one, rowcount


AUTO_INDEX_THRESHOLD_BYTES = 5 * 1024 * 1024
INDEX_REBUILD_HOLD_UNTIL = "9999-12-31T23:59:59+00:00"


@dataclass(frozen=True)
class IndexOutboxEvent:
    id: str
    knowledge_base_id: str
    event_type: str
    attempts: int


@dataclass(frozen=True)
class DocumentSyncJob:
    id: str
    knowledge_base_id: str
    document_id: str
    operation: str
    source_sha256: str | None
    index_document_id: str | None
    index_approved: bool
    attempts: int


@dataclass(frozen=True)
class PendingIndexGeneration:
    job_id: str
    document_id: str
    file_name: str
    file_size_bytes: int
    source_sha256: str
    parse_status: str


class KnowledgeIndexRepository:
    """Durable outbox and per-document sync queue.

    Queue writes never commit. KB/document services write them in the same transaction as the
    source row, while the worker owns claim/finish commits.
    """

    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def enqueue_binding_event(self, knowledge_base_id: str, event_type: str, now: str) -> None:
        suffix = "ensure" if event_type == "binding.ensure" else "delete"
        dedupe_key = f"binding:{suffix}:{knowledge_base_id}"
        execute(
            self.connection,
            """
            insert into knowledge_index_outbox (
              id, dedupe_key, knowledge_base_id, event_type, status, attempts,
              available_at, created_at, updated_at
            ) values (?, ?, ?, ?, 'pending', 0, ?, ?, ?)
            on conflict (dedupe_key) do update set
              event_type = excluded.event_type,
              status = case
                when knowledge_index_outbox.status in ('pending', 'processing')
                  then knowledge_index_outbox.status
                else 'pending'
              end,
              available_at = case
                when knowledge_index_outbox.status in ('pending', 'processing')
                  then knowledge_index_outbox.available_at
                else excluded.available_at
              end,
              last_error = case
                when knowledge_index_outbox.status in ('pending', 'processing')
                  then knowledge_index_outbox.last_error
                else null
              end,
              processed_at = case
                when knowledge_index_outbox.status in ('pending', 'processing')
                  then knowledge_index_outbox.processed_at
                else null
              end,
              updated_at = excluded.updated_at
            """,
            (f"idxevt_{uuid4().hex}", dedupe_key, knowledge_base_id, event_type, now, now, now),
        )

    def wake_controller_unconfigured_events(self, now: str) -> int:
        """Retry configuration failures immediately once a Controller provider exists.

        Ordinary Controller failures keep their exponential backoff. This exact deployment error
        cannot recover until configuration changes, so preserving its old timer after a restart
        only delays a now-actionable lifecycle request.
        """
        cursor = execute(
            self.connection,
            """
            update knowledge_index_outbox
            set available_at = ?, updated_at = ?
            where event_type = 'binding.ensure' and status = 'pending'
              and last_error = 'No dynamic isolated LightRAG Controller is configured'
              and available_at > ?
            """,
            (now, now, now),
        )
        return rowcount(cursor)

    def wake_docling_unconfigured_jobs(self, now: str) -> int:
        """Revive active document jobs after a previously missing Docling URL is configured."""
        cursor = execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'pending', attempts = 0, available_at = ?, last_error = null,
                completed_at = null, updated_at = ?
            where operation = 'upsert' and status = 'failed'
              and last_error = 'Docling service is not configured'
              and exists (
                select 1
                from knowledge_bases kb
                join documents d on d.knowledge_base_id = kb.id
                where kb.id = knowledge_document_sync_jobs.knowledge_base_id
                  and kb.status = 'active' and kb.deleted_at is null
                  and d.id = knowledge_document_sync_jobs.document_id
                  and d.deleted_at is null
              )
            """,
            (now, now),
        )
        return rowcount(cursor)

    def next_event(self, now: str) -> IndexOutboxEvent | None:
        rows = fetch_all(
            self.connection,
            """
            select id, knowledge_base_id, event_type, attempts
            from knowledge_index_outbox
            where status = 'pending' and available_at <= ?
            order by created_at asc, id asc
            limit 20
            """,
            (now,),
        )
        for row in rows:
            cursor = execute(
                self.connection,
                """
                update knowledge_index_outbox
                set status = 'processing', attempts = attempts + 1, updated_at = ?
                where id = ? and status = 'pending'
                """,
                (now, str(row["id"])),
            )
            if rowcount(cursor) > 0:
                return IndexOutboxEvent(
                    id=str(row["id"]),
                    knowledge_base_id=str(row["knowledge_base_id"]),
                    event_type=str(row["event_type"]),
                    attempts=int(row["attempts"]) + 1,
                )
        return None

    def event_processed(self, knowledge_base_id: str, event_type: str) -> bool:
        return (
            fetch_one(
                self.connection,
                """
                select id from knowledge_index_outbox
                where knowledge_base_id = ? and event_type = ? and status = 'processed'
                limit 1
                """,
                (knowledge_base_id, event_type),
            )
            is not None
        )

    def complete_event(self, event_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_index_outbox
            set status = 'processed', last_error = null, processed_at = ?, updated_at = ?
            where id = ?
            """,
            (now, now, event_id),
        )

    def retry_event(self, event_id: str, error: str, available_at: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_index_outbox
            set status = 'pending', last_error = ?, available_at = ?, updated_at = ?
            where id = ?
            """,
            (error[:4000], available_at, now, event_id),
        )

    def enqueue_document_upsert(
        self,
        knowledge_base_id: str,
        document_id: str,
        source_sha256: str | None,
        now: str,
        *,
        pipeline_version: str | None = None,
    ) -> None:
        generation = source_sha256 or "sha-pending"
        pipeline = pipeline_version or "source-v1"
        dedupe_key = f"document:upsert:{document_id}:{generation}:{pipeline}"
        execute(
            self.connection,
            """
            insert into knowledge_document_sync_jobs (
              id, dedupe_key, knowledge_base_id, document_id, operation, source_sha256,
              status, attempts, available_at, created_at, updated_at
            )
            select ?, ?, ?, ?, 'upsert', ?, 'pending', 0, ?, ?, ?
            where exists (
              select 1 from knowledge_bases kb
              join documents d on d.knowledge_base_id = kb.id
              where kb.id = ? and kb.status = 'active' and kb.deleted_at is null
                and d.id = ? and d.deleted_at is null
            )
            on conflict (dedupe_key) do update set
              status = 'pending', attempts = 0, available_at = excluded.available_at,
              last_error = null, completed_at = null, index_approved_at = null,
              updated_at = excluded.updated_at
            where knowledge_document_sync_jobs.status = 'superseded'
            """,
            (
                f"idxjob_{uuid4().hex}",
                dedupe_key,
                knowledge_base_id,
                document_id,
                source_sha256,
                now,
                now,
                now,
                knowledge_base_id,
                document_id,
            ),
        )

    def enqueue_document_delete(
        self,
        knowledge_base_id: str,
        document_id: str,
        source_sha256: str | None,
        index_document_id: str | None,
        now: str,
        *,
        supersede_upserts: bool = True,
    ) -> None:
        identity = index_document_id or source_sha256 or "not-indexed"
        dedupe_key = f"document:delete:{document_id}:{identity}"
        if supersede_upserts:
            execute(
                self.connection,
                """
                update knowledge_document_sync_jobs
                set status = 'superseded', completed_at = ?, updated_at = ?
                where document_id = ? and operation = 'upsert'
                  and status in ('pending', 'processing', 'failed')
                """,
                (now, now, document_id),
            )
        execute(
            self.connection,
            """
            insert into knowledge_document_sync_jobs (
              id, dedupe_key, knowledge_base_id, document_id, operation, source_sha256,
              index_document_id, status, attempts, available_at, created_at, updated_at
            ) values (?, ?, ?, ?, 'delete', ?, ?, 'pending', 0, ?, ?, ?)
            on conflict (dedupe_key) do nothing
            """,
            (
                f"idxjob_{uuid4().hex}",
                dedupe_key,
                knowledge_base_id,
                document_id,
                source_sha256,
                index_document_id,
                now,
                now,
                now,
            ),
        )

    def next_document_job(self, now: str) -> DocumentSyncJob | None:
        rows = fetch_all(
            self.connection,
            """
            select id, knowledge_base_id, document_id, operation, source_sha256,
                   index_document_id, index_approved_at, attempts
            from knowledge_document_sync_jobs
            where status = 'pending' and available_at <= ?
              and (
                operation <> 'upsert'
                or exists (
                  select 1 from knowledge_bases kb
                  where kb.id = knowledge_document_sync_jobs.knowledge_base_id
                    and kb.status = 'active' and kb.deleted_at is null
                )
              )
            order by created_at asc, id asc
            limit 50
            """,
            (now,),
        )
        for row in rows:
            cursor = execute(
                self.connection,
                """
                update knowledge_document_sync_jobs
                set status = 'processing', attempts = attempts + 1, updated_at = ?
                where id = ? and status = 'pending'
                """,
                (now, str(row["id"])),
            )
            if rowcount(cursor) > 0:
                return DocumentSyncJob(
                    id=str(row["id"]),
                    knowledge_base_id=str(row["knowledge_base_id"]),
                    document_id=str(row["document_id"]),
                    operation=str(row["operation"]),
                    source_sha256=(
                        str(row["source_sha256"]) if row.get("source_sha256") is not None else None
                    ),
                    index_document_id=(
                        str(row["index_document_id"])
                        if row.get("index_document_id") is not None
                        else None
                    ),
                    index_approved=row.get("index_approved_at") is not None,
                    attempts=int(row["attempts"]) + 1,
                )
        return None

    def supersede_inactive_upserts(self, now: str) -> int:
        """Close queued generations that can no longer run after KB archive/delete.

        ``next_document_job`` intentionally skips inactive KBs, but without this reconciliation
        pass those durable rows would remain ``pending`` forever and survive a later hard GC.
        Activation can still enqueue the same generation again through the dedupe-key upsert.
        """
        cursor = execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'superseded', completed_at = ?, updated_at = ?, last_error = null
            where operation = 'upsert'
              and status = 'pending'
              and not exists (
                select 1 from knowledge_bases kb
                where kb.id = knowledge_document_sync_jobs.knowledge_base_id
                  and kb.status = 'active' and kb.deleted_at is null
              )
            """,
            (now, now),
        )
        return rowcount(cursor)

    def complete_document_job(self, job_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'succeeded', last_error = null, completed_at = ?, updated_at = ?
            where id = ?
            """,
            (now, now, job_id),
        )

    def retry_document_job(
        self,
        job_id: str,
        error: str,
        *,
        available_at: str,
        terminal: bool,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = ?, last_error = ?, available_at = ?, updated_at = ?,
                completed_at = ?
            where id = ?
            """,
            (
                "failed" if terminal else "pending",
                error[:4000],
                available_at,
                now,
                now if terminal else None,
                job_id,
            ),
        )

    def defer_document_job(self, job_id: str, *, available_at: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'pending', attempts = case when attempts > 0 then attempts - 1 else 0 end,
                available_at = ?, updated_at = ?
            where id = ?
            """,
            (available_at, now, job_id),
        )

    def supersede_document_job(self, job_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'superseded', completed_at = ?, updated_at = ?
            where id = ? and operation = 'upsert'
            """,
            (now, now, job_id),
        )

    def suspend_knowledge_base_upserts(self, knowledge_base_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'superseded', index_approved_at = null,
                completed_at = ?, updated_at = ?
            where knowledge_base_id = ? and operation = 'upsert'
              and status in ('pending', 'processing', 'failed')
            """,
            (now, now, knowledge_base_id),
        )

    def repair_processing(self, now: str) -> int:
        events = execute(
            self.connection,
            """
            update knowledge_index_outbox
            set status = 'pending', available_at = ?, updated_at = ?
            where status = 'processing'
            """,
            (now, now),
        )
        jobs = execute(
            self.connection,
            """
            update knowledge_document_sync_jobs
            set status = 'pending', available_at = ?, updated_at = ?
            where status = 'processing'
            """,
            (now, now),
        )
        return rowcount(events) + rowcount(jobs)

    def live_documents_requiring_sync(
        self, limit: int, *, pipeline_version: str
    ) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            """
            select d.id, d.knowledge_base_id, d.source_sha256, d.content_hash,
                   d.indexed_sha256, d.index_status, d.index_pipeline_version
            from documents d
            join knowledge_bases kb on kb.id = d.knowledge_base_id
            where d.deleted_at is null and kb.deleted_at is null and kb.status = 'active'
              and (
                d.source_sha256 is null
                or d.indexed_sha256 is null
                or d.indexed_sha256 <> d.source_sha256
                or d.index_status <> 'ready'
                or d.index_pipeline_version is null
                or d.index_pipeline_version <> ?
              )
            order by d.created_at asc, d.id asc
            limit ?
            """,
            (pipeline_version, limit),
        )

    def pending_index_batch(
        self, knowledge_base_id: str, *, pipeline_version: str
    ) -> list[PendingIndexGeneration]:
        rows = fetch_all(
            self.connection,
            """
            select j.id as job_id, d.id as document_id, d.file_name, d.file_size_bytes,
                   coalesce(d.source_sha256, d.content_hash) as source_sha256,
                   d.parse_status
            from documents d
            join knowledge_bases kb on kb.id = d.knowledge_base_id
            join knowledge_document_sync_jobs j
              on j.knowledge_base_id = d.knowledge_base_id
             and j.document_id = d.id and j.operation = 'upsert'
             and j.source_sha256 = coalesce(d.source_sha256, d.content_hash)
             and j.dedupe_key = (
               'document:upsert:' || d.id || ':' ||
               coalesce(d.source_sha256, d.content_hash) || ':' || ?
             )
            where d.knowledge_base_id = ? and d.deleted_at is null
              and kb.status = 'active' and kb.deleted_at is null
              and j.index_approved_at is null
              and j.status in ('pending', 'processing', 'failed')
              and (
                d.indexed_sha256 is null
                or d.indexed_sha256 <> coalesce(d.source_sha256, d.content_hash)
                or d.index_pipeline_version is null
                or d.index_pipeline_version <> ?
                or d.index_status <> 'ready'
              )
            order by d.created_at asc, d.id asc
            """,
            (pipeline_version, knowledge_base_id, pipeline_version),
        )
        return [
            PendingIndexGeneration(
                job_id=str(row["job_id"]),
                document_id=str(row["document_id"]),
                file_name=str(row["file_name"]),
                file_size_bytes=int(row["file_size_bytes"]),
                source_sha256=str(row["source_sha256"]),
                parse_status=str(row["parse_status"]),
            )
            for row in rows
        ]

    def hold_for_rebuild(self, generations: list[PendingIndexGeneration], now: str) -> None:
        for item in generations:
            if item.parse_status != "ready":
                continue
            execute(
                self.connection,
                """
                update documents
                set index_status = 'stale', last_error = null, updated_at = ?
                where id = ? and source_sha256 = ? and deleted_at is null
                """,
                (now, item.document_id, item.source_sha256),
            )
            execute(
                self.connection,
                """
                update knowledge_document_sync_jobs
                set status = 'pending', available_at = ?, last_error = null,
                    completed_at = null,
                    attempts = case
                      when status = 'processing' and attempts > 0 then attempts - 1
                      else attempts
                    end,
                    updated_at = ?
                where id = ? and status in ('pending', 'processing', 'failed')
                """,
                (INDEX_REBUILD_HOLD_UNTIL, now, item.job_id),
            )

    def approve_batch(self, generations: list[PendingIndexGeneration], now: str) -> None:
        for item in generations:
            execute(
                self.connection,
                """
                update knowledge_document_sync_jobs
                set status = 'pending', index_approved_at = ?, available_at = ?,
                    last_error = null, completed_at = null, updated_at = ?
                where id = ? and status = 'pending' and index_approved_at is null
                """,
                (now, now, now, item.job_id),
            )
            execute(
                self.connection,
                """
                update documents set index_status = 'pending', last_error = null, updated_at = ?
                where id = ? and source_sha256 = ?
                  and index_status in ('stale', 'pending', 'failed')
                """,
                (now, item.document_id, item.source_sha256),
            )

    def get_approval(self, knowledge_base_id: str, batch_token: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select * from knowledge_index_approvals
            where knowledge_base_id = ? and batch_token = ?
            limit 1
            """,
            (knowledge_base_id, batch_token),
        )

    def create_approval(
        self,
        knowledge_base_id: str,
        batch_token: str,
        document_count: int,
        total_size_bytes: int,
        approved_by: str,
        now: str,
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            insert into knowledge_index_approvals (
              batch_token, knowledge_base_id, document_count, total_size_bytes,
              approved_by, approved_at
            ) values (?, ?, ?, ?, ?, ?)
            on conflict (batch_token) do nothing
            """,
            (
                batch_token,
                knowledge_base_id,
                document_count,
                total_size_bytes,
                approved_by,
                now,
            ),
        )
        return rowcount(cursor) > 0

    def deleted_documents_requiring_cleanup(self, limit: int) -> list[dict[str, Any]]:
        return fetch_all(
            self.connection,
            """
            select id, knowledge_base_id, source_sha256, content_hash,
                   index_document_id
            from documents
            where deleted_at is not null
              and index_document_id is not null
            order by deleted_at asc, id asc
            limit ?
            """,
            (limit,),
        )

    def document_sync_source(self, document_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select d.*, kb.deleted_at as knowledge_base_deleted_at,
                   kb.status as knowledge_base_status
            from documents d
            join knowledge_bases kb on kb.id = d.knowledge_base_id
            where d.id = ?
            limit 1
            """,
            (document_id,),
        )

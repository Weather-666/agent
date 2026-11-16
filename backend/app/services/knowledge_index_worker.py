from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone

from app.clients.docling_client import DoclingClient
from app.clients.lightrag_client import LightRagClient
from app.clients.lightrag_provider import LightRagProvider, create_lightrag_provider
from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.services.document_repository import DocumentRepository
from app.services.knowledge_base_repository import KnowledgeBaseRepository
from app.services.knowledge_index_repository import (
    AUTO_INDEX_THRESHOLD_BYTES,
    DocumentSyncJob,
    IndexOutboxEvent,
    KnowledgeIndexRepository,
)
from app.services.lightrag_instance_repository import LightragInstanceRepository
from app.services.object_store import ObjectStore


logger = logging.getLogger(__name__)
_LIGHTRAG_SUCCESS = {"processed", "completed", "succeeded", "success"}
_LIGHTRAG_FAILED = {"failed", "failure", "error", "cancelled", "canceled"}
_LIGHTRAG_TERMINAL = _LIGHTRAG_SUCCESS | _LIGHTRAG_FAILED


class _DocumentDeferred(Exception):
    pass


async def reconcile_knowledge_indexes(settings: Settings) -> None:
    """Repair durable queue wake-ups before the HTTP service becomes available."""
    from app.db import open_database_connection
    from app.services.object_store import create_object_store

    try:
        store = create_object_store(settings)
    except ApiError:
        # External storage failure must not take the entire HTTP API down. Durable source rows
        # remain authoritative; the background worker retries bootstrap and upload APIs return
        # their existing typed OBJECT_STORE_UNAVAILABLE response.
        logger.warning("object store unavailable during knowledge index reconciliation")
        return
    with open_database_connection(settings) as connection:
        worker = KnowledgeIndexWorker(
            connection,
            settings,
            store,
            provider=create_lightrag_provider(settings),
        )
        worker.repair_processing()
        worker.reconcile()
        try:
            await worker.reconcile_provider()
        except ApiError:
            # A Controller outage is represented by durable provisioning state and retried by the
            # worker. It must not turn a recoverable index dependency into Backend startup failure.
            logger.warning("LightRAG Controller unavailable during startup reconciliation")


async def run_knowledge_index_worker(settings: Settings) -> None:
    """Drain durable index work with a small fixed number of independent workers."""
    docling_gate = asyncio.Semaphore(settings.docling_max_concurrency)
    lightrag_locks: dict[str, asyncio.Lock] = {}
    await asyncio.gather(
        *(
            _run_knowledge_index_worker_slot(settings, slot, docling_gate, lightrag_locks)
            for slot in range(settings.knowledge_index_worker_concurrency)
        )
    )


async def _run_knowledge_index_worker_slot(
    settings: Settings,
    slot: int,
    docling_gate: asyncio.Semaphore,
    lightrag_locks: dict[str, asyncio.Lock],
) -> None:
    from app.db import open_database_connection
    from app.services.object_store import create_object_store

    store: ObjectStore | None = None
    provider = create_lightrag_provider(settings)
    while True:
        try:
            if store is None:
                try:
                    store = create_object_store(settings)
                except ApiError:
                    logger.warning("object store unavailable; knowledge sync will retry")
                    await asyncio.sleep(settings.knowledge_index_worker_poll_seconds)
                    continue
            with open_database_connection(settings) as connection:
                worker = KnowledgeIndexWorker(
                    connection,
                    settings,
                    store,
                    provider=provider,
                    docling_gate=docling_gate,
                    lightrag_locks=lightrag_locks,
                )
                worker.reconcile()
                ran = await worker.poll_once()
            await asyncio.sleep(0 if ran else settings.knowledge_index_worker_poll_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - the durable worker loop must survive one bad item
            logger.exception("knowledge index worker slot %d iteration failed", slot)
            await asyncio.sleep(settings.knowledge_index_worker_poll_seconds)


class KnowledgeIndexWorker:
    def __init__(
        self,
        connection: DatabaseConnection,
        settings: Settings,
        object_store: ObjectStore,
        *,
        provider: LightRagProvider | None,
        docling_gate: asyncio.Semaphore | None = None,
        lightrag_locks: dict[str, asyncio.Lock] | None = None,
    ) -> None:
        self.connection = connection
        self.settings = settings
        self.store = object_store
        self.provider = provider
        self.docling_gate = docling_gate or asyncio.Semaphore(settings.docling_max_concurrency)
        self.lightrag_locks = lightrag_locks if lightrag_locks is not None else {}
        self.queue = KnowledgeIndexRepository(connection)
        self.instances = LightragInstanceRepository(connection)
        self.kbs = KnowledgeBaseRepository(connection)
        self.docs = DocumentRepository(connection)

    def repair_processing(self) -> None:
        repaired = self.queue.repair_processing(_now_iso())
        self.connection.commit()
        if repaired:
            logger.warning("requeued %d interrupted knowledge index work items", repaired)

    def reconcile(self) -> None:
        """Recreate missing wake-ups from source rows without external side effects."""
        now = _now_iso()
        limit = self.settings.knowledge_index_reconcile_batch_size
        if self.provider is not None:
            self.queue.wake_controller_unconfigured_events(now)
        if self.settings.docling_base_url:
            self.queue.wake_docling_unconfigured_jobs(now)
        self.queue.supersede_inactive_upserts(now)
        for row in self.kbs.list_index_lifecycle_rows(limit):
            knowledge_base_id = str(row["id"])
            if row.get("deleted_at") is not None:
                if row.get("base_url") is not None or not self.queue.event_processed(
                    knowledge_base_id, "binding.delete"
                ):
                    self.queue.enqueue_binding_event(knowledge_base_id, "binding.delete", now)
                continue
            binding_ready = (
                row.get("base_url") is not None
                and row.get("workspace") is not None
                and str(row.get("binding_status") or "ready") == "ready"
            )
            if not binding_ready or str(row.get("index_status") or "") != "ready":
                if str(row.get("index_status") or "") != "failed":
                    self.kbs.set_index_state(
                        knowledge_base_id,
                        "provisioning",
                        error=None,
                        updated_at=now,
                    )
                self.queue.enqueue_binding_event(knowledge_base_id, "binding.ensure", now)

        for row in self.queue.live_documents_requiring_sync(
            limit,
            pipeline_version=self.settings.knowledge_index_pipeline_version,
        ):
            source_sha = row.get("source_sha256") or row.get("content_hash")
            self.queue.enqueue_document_upsert(
                str(row["knowledge_base_id"]),
                str(row["id"]),
                str(source_sha) if source_sha is not None else None,
                now,
                pipeline_version=self.settings.knowledge_index_pipeline_version,
            )
        for row in self.queue.deleted_documents_requiring_cleanup(limit):
            source_sha = row.get("source_sha256") or row.get("content_hash")
            index_document_id = row.get("index_document_id")
            self.queue.enqueue_document_delete(
                str(row["knowledge_base_id"]),
                str(row["id"]),
                str(source_sha) if source_sha is not None else None,
                str(index_document_id) if index_document_id is not None else None,
                now,
            )
        self.connection.commit()

    async def reconcile_provider(self) -> None:
        """Compare live KB source rows with Controller-owned instances after a restart."""
        if self.provider is None:
            return
        live_ids = self.kbs.list_live_index_ids()
        result = await self.provider.reconcile(live_ids)
        now = _now_iso()
        missing_ids = set(result.get("missingKnowledgeBaseIds") or [])
        for knowledge_base_id in live_ids:
            if knowledge_base_id in missing_ids:
                self.kbs.set_index_state(
                    knowledge_base_id, "provisioning", error=None, updated_at=now
                )
            # Existing containers can acquire a new address after a Docker restart.
            self.queue.enqueue_binding_event(knowledge_base_id, "binding.ensure", now)
        self.connection.commit()
        # Unknown Controller instances have no live source row and are safe to reclaim using the
        # Controller's deterministic, label-checked delete contract.
        for knowledge_base_id in result.get("orphanKnowledgeBaseIds") or []:
            await self.provider.delete(str(knowledge_base_id))

    async def poll_once(self) -> bool:
        event = self.queue.next_event(_now_iso())
        if event is not None:
            self.connection.commit()
            await self._process_event(event)
            return True
        job = self.queue.next_document_job(_now_iso())
        if job is None:
            return False
        self.connection.commit()
        await self._process_document_job(job)
        return True

    async def _process_event(self, event: IndexOutboxEvent) -> None:
        try:
            if event.event_type == "binding.delete":
                await self._delete_binding(event.knowledge_base_id)
            else:
                await self._ensure_binding(event.knowledge_base_id)
            now = _now_iso()
            self.queue.complete_event(event.id, now)
            self.connection.commit()
        except ApiError as exc:
            self._retry_event(event, exc)
        except Exception as exc:  # noqa: BLE001 - persist a retryable provider failure
            self._retry_event(
                event,
                ApiError(
                    503,
                    "LIGHTRAG_PROVISIONING_FAILED",
                    "LightRAG lifecycle operation failed",
                    {"reasonType": type(exc).__name__},
                ),
            )

    async def _ensure_binding(self, knowledge_base_id: str) -> None:
        kb = self.kbs.get(knowledge_base_id)
        if kb is None:
            return
        existing = self.instances.get_binding(knowledge_base_id)
        now = _now_iso()
        if self.provider is not None:
            if existing is None:
                instance = await self.provider.ensure(knowledge_base_id)
            else:
                try:
                    instance = await self.provider.health(knowledge_base_id)
                except ApiError as exc:
                    if exc.details.get("controllerStatus") != 404:
                        raise
                    instance = await self.provider.ensure(knowledge_base_id)
            self.instances.upsert_ready(
                knowledge_base_id,
                provider=instance.provider,
                provider_ref=instance.provider_ref,
                base_url=instance.base_url,
                workspace=instance.workspace,
                now=now,
            )
            self.kbs.set_index_state(knowledge_base_id, "ready", error=None, updated_at=now)
            return

        raise ApiError(
            503,
            "LIGHTRAG_CONTROLLER_UNCONFIGURED",
            "No dynamic isolated LightRAG Controller is configured",
            {"knowledgeBaseId": knowledge_base_id, "retryable": True},
        )

    async def _delete_binding(self, knowledge_base_id: str) -> None:
        binding = self.instances.get_binding(knowledge_base_id)
        if binding is not None and self.provider is None:
            raise ApiError(
                503,
                "LIGHTRAG_CONTROLLER_UNCONFIGURED",
                "Dynamic LightRAG binding cannot be deleted without its Controller",
                {"knowledgeBaseId": knowledge_base_id, "retryable": True},
            )
        if self.provider is not None:
            # Idempotent even when an ensure succeeded but its DB binding commit was lost.
            await self.provider.delete(knowledge_base_id)
        self.instances.remove(knowledge_base_id)
        self.kbs.set_index_state(knowledge_base_id, "deleting", error=None, updated_at=_now_iso())

    def _retry_event(self, event: IndexOutboxEvent, exc: ApiError) -> None:
        now = _now_iso()
        self.instances.mark_failed(event.knowledge_base_id, exc.message, now)
        self.kbs.set_index_state(
            event.knowledge_base_id, "failed", error=exc.message, updated_at=now
        )
        self.queue.retry_event(
            event.id,
            exc.message,
            self._retry_at(event.attempts),
            now,
        )
        self.connection.commit()

    async def _process_document_job(self, job: DocumentSyncJob) -> None:
        try:
            if job.operation == "delete":
                await self._delete_document(job)
            else:
                await self._upsert_document(job)
            self.queue.complete_document_job(job.id, _now_iso())
            self.connection.commit()
        except _DocumentDeferred:
            return
        except ApiError as exc:
            self._retry_document_job(job, exc)
        except Exception as exc:  # noqa: BLE001 - never strand a claimed durable job
            logger.exception(
                "knowledge document job failed unexpectedly: job_id=%s document_id=%s",
                job.id,
                job.document_id,
            )
            self._retry_document_job(
                job,
                ApiError(
                    503,
                    "KNOWLEDGE_INDEX_UNEXPECTED_FAILURE",
                    "Knowledge indexing failed unexpectedly and will retry",
                    {"reasonType": type(exc).__name__},
                ),
            )

    def _retry_document_job(self, job: DocumentSyncJob, exc: ApiError) -> None:
        retryable = exc.code in {
            "LIGHTRAG_INSTANCE_NOT_ASSIGNED",
            "LIGHTRAG_INSTANCE_NOT_READY",
            "LIGHTRAG_CONTROLLER_UNAVAILABLE",
            "LIGHTRAG_REQUEST_FAILED",
            "LIGHTRAG_INGESTION_IN_PROGRESS",
            "LIGHTRAG_DELETE_BUSY",
            "LIGHTRAG_DELETE_TIMEOUT",
        }
        # Dependency/busy failures stay durably retryable with capped backoff. Deterministic
        # parse/index failures become terminal at the configured attempt limit; startup repair
        # can revive them after an operator changes the pipeline or source.
        terminal = exc.code == "KB_DOCUMENT_DUPLICATE_CONTENT" or (
            job.attempts >= self.settings.knowledge_index_max_attempts and not retryable
        )
        now = _now_iso()
        source = self.queue.document_sync_source(job.document_id)
        if source is not None and source.get("deleted_at") is None:
            next_status = "failed" if terminal else "pending"
            self.docs.set_index_status(job.document_id, next_status, error=exc.message, now=now)
            if str(source.get("parse_status") or "") != "ready":
                self.docs.set_parse_status(
                    job.document_id, next_status, error=exc.message, now=now
                )
        self.queue.retry_document_job(
            job.id,
            exc.message,
            available_at=self._retry_at(job.attempts),
            terminal=terminal,
            now=now,
        )
        self.connection.commit()

    async def _upsert_document(self, job: DocumentSyncJob) -> None:
        source = self.queue.document_sync_source(job.document_id)
        if source is None:
            return
        if (
            source.get("deleted_at") is not None
            or source.get("knowledge_base_deleted_at") is not None
        ):
            index_document_id = source.get("index_document_id")
            self.queue.enqueue_document_delete(
                job.knowledge_base_id,
                job.document_id,
                job.source_sha256,
                str(index_document_id) if index_document_id is not None else None,
                _now_iso(),
            )
            return

        self._stop_if_inactive(job)
        raw = self.store.read(str(source["storage_key"]))
        actual_sha = hashlib.sha256(raw).hexdigest()
        expected_sha = source.get("source_sha256") or source.get("content_hash")
        if expected_sha is not None and str(expected_sha) != actual_sha:
            raise ApiError(
                409,
                "KB_SOURCE_VERSION_MISMATCH",
                "The immutable source object does not match its recorded SHA",
                {"documentId": job.document_id},
            )
        if job.source_sha256 is not None and job.source_sha256 != actual_sha:
            # A newer immutable generation won. Reconciliation will enqueue that generation.
            return
        canonical = self.docs.find_live_document_by_source_sha(
            job.knowledge_base_id, actual_sha
        )
        if canonical is not None and canonical.id != job.document_id:
            raise ApiError(
                409,
                "KB_DOCUMENT_DUPLICATE_CONTENT",
                "The knowledge base already contains a document with the same content",
                {
                    "duplicateDocumentId": canonical.id,
                    "duplicateFileName": canonical.fileName,
                },
            )
        now = _now_iso()
        self.docs.set_source_sha(job.document_id, actual_sha, now)
        if (
            str(source.get("index_status") or "") == "ready"
            and str(source.get("indexed_sha256") or "") == actual_sha
            and source.get("index_document_id") is not None
            and str(source.get("index_pipeline_version") or "")
            == self.settings.knowledge_index_pipeline_version
        ):
            return

        if (
            str(source.get("parse_status") or "") == "ready"
            and source.get("markdown_storage_key") is not None
        ):
            markdown = self.store.read(str(source["markdown_storage_key"])).decode("utf-8")
        else:
            self.docs.set_parse_status(job.document_id, "processing", now=now)
            self.connection.commit()
            started = time.perf_counter()
            async with self.docling_gate:
                markdown = await DoclingClient(self.settings).convert_to_markdown(
                    str(source["file_name"]), raw
                )
            logger.info(
                "knowledge_index_phase phase=docling document_id=%s duration_seconds=%.3f",
                job.document_id,
                time.perf_counter() - started,
            )
            markdown_bytes = markdown.encode("utf-8")
            markdown_sha = hashlib.sha256(markdown_bytes).hexdigest()
            markdown_key = (
                f"knowledge-bases/{job.knowledge_base_id}/documents/{job.document_id}/"
                f"markdown/{actual_sha}/{markdown_sha}.md"
            )
            self.store.put(
                markdown_key, markdown_bytes, content_type="text/markdown; charset=utf-8"
            )
            self.docs.set_markdown_artifact(
                job.document_id,
                source_sha256=actual_sha,
                storage_key=markdown_key,
                markdown_sha256=markdown_sha,
                now=_now_iso(),
            )
            self.connection.commit()

        markdown_sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        canonical_markdown = self.docs.find_live_document_by_markdown_sha(
            job.knowledge_base_id, markdown_sha
        )
        if canonical_markdown is not None and canonical_markdown.id != job.document_id:
            raise ApiError(
                409,
                "KB_DOCUMENT_DUPLICATE_CONTENT",
                "The knowledge base already contains a document with the same parsed content",
                {
                    "duplicateDocumentId": canonical_markdown.id,
                    "duplicateFileName": canonical_markdown.fileName,
                },
            )

        self._stop_if_inactive(job)
        pending = self.queue.pending_index_batch(
            job.knowledge_base_id,
            pipeline_version=self.settings.knowledge_index_pipeline_version,
        )
        if (
            not job.index_approved
            and sum(item.file_size_bytes for item in pending) > AUTO_INDEX_THRESHOLD_BYTES
        ):
            self.queue.hold_for_rebuild(pending, _now_iso())
            self.connection.commit()
            raise _DocumentDeferred

        binding = self.instances.require_binding(job.knowledge_base_id)
        self.docs.set_index_status(job.document_id, "processing", now=_now_iso())
        self.connection.commit()
        self._stop_if_inactive(job)
        lightrag = self._client(binding.base_url)
        file_source = _file_source(job.knowledge_base_id, job.document_id, actual_sha)
        source = self.queue.document_sync_source(job.document_id) or source
        existing_track_id = str(source.get("lightrag_track_id") or "")
        if existing_track_id:
            try:
                track = await self._poll_until_terminal(job, lightrag, existing_track_id)
            except ApiError as exc:
                if exc.code != "LIGHTRAG_TRACK_NOT_FOUND":
                    raise
            else:
                if await self._apply_terminal_track(
                    job,
                    source_sha256=actual_sha,
                    file_source=file_source,
                    track_id=existing_track_id,
                    track=track,
                    lightrag=lightrag,
                ):
                    return
            self.docs.clear_pending_index_track(job.document_id, _now_iso())
            self.connection.commit()

        started = time.perf_counter()
        async with self._lightrag_lock(job.knowledge_base_id):
            existing = await lightrag.find_document_by_file_source(file_source)
            if existing is not None and await self._reuse_existing_document(
                job,
                source_sha256=actual_sha,
                file_source=file_source,
                existing=existing,
                lightrag=lightrag,
            ):
                return
            try:
                result = await lightrag.insert_text(
                    markdown,
                    file_source,
                    timeout=self.settings.lightrag_insert_timeout_seconds,
                    chunking=self._chunking(),
                )
            except ApiError as exc:
                if exc.code != "LIGHTRAG_DOCUMENT_CONFLICT":
                    raise
                conflict = await lightrag.find_document_by_file_source(file_source)
                if conflict is None:
                    raise
                if await self._reuse_existing_document(
                    job,
                    source_sha256=actual_sha,
                    file_source=file_source,
                    existing=conflict,
                    lightrag=lightrag,
                ):
                    return
                result = await lightrag.insert_text(
                    markdown,
                    file_source,
                    timeout=self.settings.lightrag_insert_timeout_seconds,
                    chunking=self._chunking(),
                )
        logger.info(
            "knowledge_index_phase phase=lightrag_submit document_id=%s duration_seconds=%.3f",
            job.document_id,
            time.perf_counter() - started,
        )
        track_id = str(result.get("track_id") or "")
        if not track_id:
            raise ApiError(
                502,
                "LIGHTRAG_INSERT_INVALID_RESPONSE",
                "LightRAG insert did not return a tracking id",
            )
        self.docs.set_lightrag_track_id(job.document_id, track_id, _now_iso())
        self.connection.commit()
        track = await self._poll_until_terminal(job, lightrag, track_id)
        await self._apply_terminal_track(
            job,
            source_sha256=actual_sha,
            file_source=file_source,
            track_id=track_id,
            track=track,
            lightrag=lightrag,
        )

    async def _reuse_existing_document(
        self,
        job: DocumentSyncJob,
        *,
        source_sha256: str,
        file_source: str,
        existing: dict,
        lightrag: LightRagClient,
    ) -> bool:
        """Resolve an idempotent file_source without issuing another insert request."""
        document_id = str(existing.get("id") or "")
        status = str(existing.get("status") or "").lower()
        track_id = str(existing.get("track_id") or "")
        if document_id and status in _LIGHTRAG_SUCCESS:
            self._activate_index_generation(job, document_id, track_id or None, source_sha256)
            return True
        if status not in _LIGHTRAG_FAILED:
            if track_id:
                self.docs.set_lightrag_track_id(job.document_id, track_id, _now_iso())
                self.connection.commit()
                track = await self._poll_until_terminal(job, lightrag, track_id)
                return await self._apply_terminal_track(
                    job,
                    source_sha256=source_sha256,
                    file_source=file_source,
                    track_id=track_id,
                    track=track,
                    lightrag=lightrag,
                )
            raise ApiError(
                409,
                "LIGHTRAG_INGESTION_IN_PROGRESS",
                "LightRAG is still processing the existing idempotent document",
                {
                    "documentId": document_id,
                    "status": status or "processing",
                    "retryable": True,
                },
            )
        if not document_id:
            raise ApiError(
                502,
                "LIGHTRAG_TRACK_INVALID_RESPONSE",
                "LightRAG conflict document omitted its id",
            )
        await self._delete_and_wait(lightrag, document_id)
        return False

    async def _delete_document(self, job: DocumentSyncJob) -> None:
        binding = self.instances.get_binding(job.knowledge_base_id)
        source = self.queue.document_sync_source(job.document_id)
        index_document_id = job.index_document_id
        if not index_document_id and source is not None:
            value = source.get("index_document_id")
            index_document_id = str(value) if value is not None else None
        if binding is not None and binding.status == "ready" and index_document_id:
            async with self._lightrag_lock(job.knowledge_base_id):
                await self._delete_and_wait(self._client(binding.base_url), index_document_id)
        current_index_id = None
        if source is not None:
            value = source.get("index_document_id")
            current_index_id = str(value) if value is not None else None
        if source is not None and (
            job.index_document_id is None or current_index_id == index_document_id
        ):
            self.docs.clear_index_result(job.document_id, _now_iso())

    async def _poll_until_terminal(
        self, job: DocumentSyncJob, lightrag: LightRagClient, track_id: str
    ) -> dict:
        started = time.perf_counter()
        track = await lightrag.track_status(track_id)
        documents = track.get("documents") or []
        logger.info(
            "knowledge_index_phase phase=track_poll document_id=%s track_id=%s duration_seconds=%.3f",
            job.document_id,
            track_id,
            time.perf_counter() - started,
        )
        if documents and all(
            str(item.get("status") or "").lower() in _LIGHTRAG_TERMINAL for item in documents
        ):
            return track
        now = _now_iso()
        self.queue.defer_document_job(
            job.id,
            available_at=(
                datetime.now(timezone.utc)
                + timedelta(seconds=self.settings.lightrag_poll_max_seconds)
            ).isoformat(),
            now=now,
        )
        self.connection.commit()
        raise _DocumentDeferred

    async def _apply_terminal_track(
        self,
        job: DocumentSyncJob,
        *,
        source_sha256: str,
        file_source: str,
        track_id: str,
        track: dict,
        lightrag: LightRagClient,
    ) -> bool:
        documents = track.get("documents") or []
        document = documents[0] if len(documents) == 1 else {}
        status = str(document.get("status") or "").lower()
        index_document_id = str(document.get("id") or "")
        tracked_source = str(document.get("file_path") or "")
        if status in _LIGHTRAG_FAILED:
            if index_document_id:
                await self._delete_and_wait(lightrag, index_document_id)
            self.docs.clear_pending_index_track(job.document_id, _now_iso())
            self.connection.commit()
            raise ApiError(
                502,
                "LIGHTRAG_INGESTION_FAILED",
                str(document.get("error_msg") or "LightRAG ingestion failed"),
            )
        if status not in _LIGHTRAG_SUCCESS or not index_document_id:
            raise ApiError(
                502,
                "LIGHTRAG_TRACK_INVALID_RESPONSE",
                "LightRAG terminal status omitted a successful document identity",
            )
        if tracked_source not in {file_source, file_source.rsplit("/", 1)[-1]}:
            await self._delete_and_wait(lightrag, index_document_id)
            self.docs.clear_pending_index_track(job.document_id, _now_iso())
            self.connection.commit()
            raise ApiError(
                409,
                "LIGHTRAG_TRACK_SOURCE_MISMATCH",
                "LightRAG ingestion track belongs to a different source generation",
                {"trackId": track_id},
            )
        current = self.queue.document_sync_source(job.document_id)
        if (
            current is None
            or current.get("deleted_at") is not None
            or str(current.get("knowledge_base_status") or "") != "active"
            or str(current.get("source_sha256") or "") != source_sha256
        ):
            await self._delete_and_wait(lightrag, index_document_id)
            return True
        self._activate_index_generation(job, index_document_id, track_id, source_sha256)
        return True

    def _stop_if_inactive(self, job: DocumentSyncJob) -> None:
        source = self.queue.document_sync_source(job.document_id)
        if source is not None and str(source.get("knowledge_base_status") or "") == "active":
            return
        now = _now_iso()
        self.queue.supersede_document_job(job.id, now)
        self.connection.commit()
        raise _DocumentDeferred

    def _activate_index_generation(
        self,
        job: DocumentSyncJob,
        index_document_id: str,
        track_id: str | None,
        source_sha256: str,
    ) -> None:
        source = self.queue.document_sync_source(job.document_id) or {}
        old_index_id = source.get("index_document_id")
        old_source_sha = source.get("indexed_sha256")
        now = _now_iso()
        self.docs.set_index_result(
            job.document_id,
            status="ready",
            index_document_id=index_document_id,
            lightrag_track_id=track_id,
            indexed_sha256=source_sha256,
            pipeline_version=self.settings.knowledge_index_pipeline_version,
            now=now,
        )
        if old_index_id is not None and str(old_index_id) != index_document_id:
            self.queue.enqueue_document_delete(
                job.knowledge_base_id,
                job.document_id,
                str(old_source_sha) if old_source_sha is not None else None,
                str(old_index_id),
                now,
                supersede_upserts=False,
            )

    async def _delete_and_wait(self, lightrag: LightRagClient, document_id: str) -> None:
        status = await lightrag.delete_document(document_id)
        if status == "not_found":
            return
        await lightrag.wait_document_deleted(
            document_id,
            timeout=self.settings.lightrag_delete_timeout_seconds,
            poll_initial=self.settings.lightrag_poll_initial_seconds,
            poll_max=self.settings.lightrag_poll_max_seconds,
        )

    def _lightrag_lock(self, knowledge_base_id: str) -> asyncio.Lock:
        return self.lightrag_locks.setdefault(knowledge_base_id, asyncio.Lock())

    def _chunking(self) -> dict:
        return {
            "strategy": "fixed_token",
            "params": {
                "chunk_token_size": self.settings.lightrag_chunk_token_size,
                "chunk_overlap_token_size": (self.settings.lightrag_chunk_overlap_token_size),
            },
        }

    def _retry_at(self, attempt: int) -> str:
        delay = min(
            self.settings.knowledge_index_retry_max_seconds,
            self.settings.knowledge_index_retry_base_seconds * (2 ** min(max(attempt - 1, 0), 8)),
        )
        return (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()

    def _client(self, base_url: str) -> LightRagClient:
        return LightRagClient(
            base_url,
            self.settings.lightrag_api_key,
            timeout=self.settings.lightrag_timeout_seconds,
        )


def _file_source(knowledge_base_id: str, document_id: str, source_sha256: str) -> str:
    return f"kb-{knowledge_base_id}--doc-{document_id}--{source_sha256[:16]}.md"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

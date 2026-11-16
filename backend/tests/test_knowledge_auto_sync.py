from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.clients.docling_client import DoclingClient
from app.clients.lightrag_client import LightRagClient
from app.clients.lightrag_provider import ProvisionedLightRag
from app.core.config import Settings
from app.core.errors import ApiError
from app.db import migrate_database, open_database_connection
from app.domain.auth import PlatformRole, Principal
from app.domain.knowledge import CompleteUploadRequest, CreateKnowledgeBaseRequest, UploadUrlRequest
from app.services.document_repository import DocumentRepository
from app.services.document_service import DocumentService
from app.services.knowledge_base_repository import KnowledgeBaseRepository
from app.services.knowledge_base_service import KnowledgeBaseService
from app.services.knowledge_index_approval_service import KnowledgeIndexApprovalService
from app.services.knowledge_index_repository import (
    AUTO_INDEX_THRESHOLD_BYTES,
    INDEX_REBUILD_HOLD_UNTIL,
    KnowledgeIndexRepository,
)
from app.services.knowledge_index_worker import KnowledgeIndexWorker
from app.services.lightrag_instance_repository import LightragInstanceRepository
from app.services.object_store import LocalObjectStore


class FakeProvider:
    def __init__(self) -> None:
        self.instances: dict[str, ProvisionedLightRag] = {}
        self.deleted: list[str] = []

    async def ensure(self, knowledge_base_id: str) -> ProvisionedLightRag:
        return self.instances.setdefault(
            knowledge_base_id,
            ProvisionedLightRag(
                provider="fake",
                provider_ref=f"instance-{knowledge_base_id}",
                base_url=f"http://instance-{knowledge_base_id}:9621",
                workspace=f"workspace_{knowledge_base_id}",
                status="ready",
            ),
        )

    async def health(self, knowledge_base_id: str) -> ProvisionedLightRag:
        try:
            return self.instances[knowledge_base_id]
        except KeyError as exc:
            raise ApiError(
                404,
                "LIGHTRAG_PROVISIONING_FAILED",
                "missing",
                {"controllerStatus": 404},
            ) from exc

    async def delete(self, knowledge_base_id: str) -> None:
        self.instances.pop(knowledge_base_id, None)
        self.deleted.append(knowledge_base_id)

    async def reconcile(self, knowledge_base_ids: list[str]) -> dict:
        requested = set(knowledge_base_ids)
        managed = set(self.instances)
        return {
            "managedKnowledgeBaseIds": sorted(managed),
            "missingKnowledgeBaseIds": sorted(requested - managed),
            "orphanKnowledgeBaseIds": sorted(managed - requested),
        }


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'automatic-index.sqlite3'}",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
        lightrag_insert_timeout_seconds=1,
        lightrag_delete_timeout_seconds=1,
        lightrag_poll_initial_seconds=0.001,
        lightrag_poll_max_seconds=0.001,
        knowledge_index_retry_base_seconds=0.001,
        knowledge_index_retry_max_seconds=0.001,
        knowledge_index_max_attempts=3,
    )


def _principal() -> Principal:
    return Principal(
        user_id="platform_admin",
        email="admin@example.com",
        platform_roles=[PlatformRole.ADMIN],
        platform_permissions=[
            "kb:create",
            "kb:delete",
            "doc:create",
            "doc:update",
            "doc:delete",
        ],
    )


def _prepare(settings: Settings) -> None:
    migrate_database(settings)
    with open_database_connection(settings) as connection:
        connection.execute(
            """
            insert into users (id, email, password_hash, name, status)
            values ('platform_admin', 'admin@example.com', 'hash', 'Admin', 'active')
            on conflict (id) do nothing
            """
        )
        connection.commit()


def _mock_successful_indexing(
    monkeypatch: pytest.MonkeyPatch, before_convert=None
) -> dict[str, str]:
    indexed_sources: dict[str, str] = {}

    async def convert(_self, _name: str, raw: bytes) -> str:
        if before_convert is not None:
            before_convert()
        return raw.decode()

    async def insert(
        _self, _text: str, source: str, *, timeout: float, chunking: dict | None = None
    ) -> dict:
        track_id = f"track-{len(indexed_sources) + 1}"
        indexed_sources[track_id] = source
        return {"track_id": track_id}

    async def track(_self, track_id: str) -> dict:
        return {
            "documents": [
                {
                    "id": f"index-{track_id}",
                    "status": "processed",
                    "file_path": indexed_sources[track_id],
                }
            ]
        }

    async def find(_self, _source: str) -> None:
        return None

    monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert)
    monkeypatch.setattr(LightRagClient, "insert_text", insert)
    monkeypatch.setattr(LightRagClient, "track_status", track)
    monkeypatch.setattr(LightRagClient, "find_document_by_file_source", find)
    return indexed_sources


def test_pipeline_version_is_part_of_document_sync_generation(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Pipeline generation")
        document = _upload(connection, store, settings, kb.id, b"same immutable bytes")
        queue = KnowledgeIndexRepository(connection)
        queue.enqueue_document_upsert(
            kb.id,
            document.id,
            document.sourceSha,
            _now(),
            pipeline_version="docling-ocr-locator-v3",
        )
        queue.enqueue_document_upsert(
            kb.id,
            document.id,
            document.sourceSha,
            _now(),
            pipeline_version="docling-ocr-locator-v3",
        )
        connection.commit()

        jobs = connection.execute(
            "select dedupe_key from knowledge_document_sync_jobs where document_id = ?",
            (document.id,),
        ).fetchall()
        assert len(jobs) == 2
        assert sum("docling-ocr-locator-v3" in row["dedupe_key"] for row in jobs) == 1


@pytest.mark.asyncio
async def test_large_batch_waits_for_explicit_rebuild_without_document_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    provider = FakeProvider()
    indexed_sources = _mock_successful_indexing(monkeypatch)

    with open_database_connection(settings) as connection:
        exact_kb = _create_kb(connection, "Exact automatic threshold")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        exact = _upload(
            connection,
            store,
            settings,
            exact_kb.id,
            b"x" * AUTO_INDEX_THRESHOLD_BYTES,
        )
        assert await worker.poll_once()
        assert (
            DocumentRepository(connection).get_document(exact_kb.id, exact.id).indexStatus
            == "ready"
        )
        assert (
            DocumentRepository(connection)
            .get_document(exact_kb.id, exact.id)
            .indexPipelineVersion
            == settings.knowledge_index_pipeline_version
        )

        batch_kb = _create_kb(connection, "Explicit rebuild batch")
        await _drain_binding_events(worker, 1)
        part_size = AUTO_INDEX_THRESHOLD_BYTES // 2 + 1
        first = _upload(
            connection, store, settings, batch_kb.id, b"a" * part_size, file_name="a.md"
        )
        second = _upload(
            connection, store, settings, batch_kb.id, b"b" * part_size, file_name="b.md"
        )

        assert await worker.poll_once()
        review_service = KnowledgeIndexApprovalService(
            connection, pipeline_version=settings.knowledge_index_pipeline_version
        )
        assert review_service.current(_principal(), batch_kb.id).status == "pending_parse"
        assert await worker.poll_once()
        review = review_service.current(_principal(), batch_kb.id)
        assert review.status == "review_required"
        assert review.documentCount == 2
        assert review.totalSizeBytes == part_size * 2
        assert review.batchToken
        for document in (first, second):
            paused = DocumentRepository(connection).get_document(batch_kb.id, document.id)
            assert paused is not None and paused.indexStatus == "stale"
            assert paused.lastError is None
        held_jobs = connection.execute(
            """
            select status, available_at from knowledge_document_sync_jobs
            where knowledge_base_id = ?
            """,
            (batch_kb.id,),
        ).fetchall()
        assert {row["status"] for row in held_jobs} == {"pending"}
        assert {row["available_at"] for row in held_jobs} == {INDEX_REBUILD_HOLD_UNTIL}
        assert len(indexed_sources) == 1

    # A restart preserves the cost gate instead of silently releasing the large batch.
    with open_database_connection(settings) as connection:
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        worker.repair_processing()
        worker.reconcile()
        assert not await worker.poll_once()

        review_service = KnowledgeIndexApprovalService(
            connection, pipeline_version=settings.knowledge_index_pipeline_version
        )
        rebuilt = review_service.approve(
            _principal(), batch_kb.id, review.batchToken, request_id="rebuild-index"
        )
        duplicate = review_service.approve(
            _principal(), batch_kb.id, review.batchToken, request_id="rebuild-index-again"
        )
        assert rebuilt.status == duplicate.status == "approved"
        assert (
            connection.execute(
                "select count(*) as count from knowledge_index_approvals where batch_token = ?",
                (review.batchToken,),
            ).fetchone()["count"]
            == 1
        )

        assert await worker.poll_once()
        assert await worker.poll_once()
        for document in (first, second):
            ready = DocumentRepository(connection).get_document(batch_kb.id, document.id)
            assert ready is not None and ready.indexStatus == "ready"


@pytest.mark.asyncio
async def test_unexpected_worker_error_requeues_claimed_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    provider = FakeProvider()

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Retry unexpected failure")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"retry me")

        def fail_read(*_args, **_kwargs):
            raise RuntimeError("boom")

        monkeypatch.setattr(store, "read", fail_read)

        assert await worker.poll_once()
        queued = connection.execute(
            "select status, last_error from knowledge_document_sync_jobs where document_id = ?",
            (document.id,),
        ).fetchone()
        current = DocumentRepository(connection).get_document(kb.id, document.id)
        assert queued["status"] == "pending"
        assert queued["last_error"] == "Knowledge indexing failed unexpectedly and will retry"
        assert current is not None and current.indexStatus == "pending"


@pytest.mark.asyncio
async def test_archive_during_parse_stops_indexing_and_activation_requeues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    provider = FakeProvider()

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Archive gate")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"archive while parsing")

        def archive_during_convert() -> None:
            KnowledgeBaseService(connection).archive(
                _principal(), kb.id, request_id="archive-during-parse"
            )

        indexed_sources = _mock_successful_indexing(monkeypatch, archive_during_convert)

        assert await worker.poll_once()
        stopped = DocumentRepository(connection).get_document(kb.id, document.id)
        assert stopped is not None and stopped.parseStatus == "ready"
        assert stopped.indexStatus != "ready"
        assert indexed_sources == {}

        KnowledgeBaseService(connection).activate(
            _principal(), kb.id, request_id="activate-after-parse"
        )
        worker.reconcile()
        assert await worker.poll_once()
        ready = DocumentRepository(connection).get_document(kb.id, document.id)
        assert ready is not None and ready.indexStatus == "ready"
        assert len(indexed_sources) == 1


@pytest.mark.asyncio
async def test_reconcile_supersedes_queued_upsert_for_archived_kb_and_activation_requeues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    provider = FakeProvider()

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Archive queued generation")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"queued before archive")

        KnowledgeBaseService(connection).archive(
            _principal(), kb.id, request_id="archive-before-claim"
        )
        worker.reconcile()
        queued = connection.execute(
            "select status, completed_at from knowledge_document_sync_jobs where document_id = ?",
            (document.id,),
        ).fetchone()
        assert queued["status"] == "superseded"
        assert queued["completed_at"] is not None
        assert KnowledgeIndexRepository(connection).next_document_job(
            datetime.now(timezone.utc).isoformat()
        ) is None

        indexed_sources = _mock_successful_indexing(monkeypatch)
        KnowledgeBaseService(connection).activate(
            _principal(), kb.id, request_id="activate-after-supersede"
        )
        worker.reconcile()
        assert await worker.poll_once()
        ready = DocumentRepository(connection).get_document(kb.id, document.id)
        assert ready is not None and ready.indexStatus == "ready"
        assert len(indexed_sources) == 1


def _create_kb(connection, name: str):
    return KnowledgeBaseService(connection).create(
        _principal(), CreateKnowledgeBaseRequest(name=name), request_id=f"create-{name}"
    )


async def _drain_binding_events(worker: KnowledgeIndexWorker, count: int) -> None:
    for _ in range(count):
        assert await worker.poll_once()


def _upload(
    connection,
    store: LocalObjectStore,
    settings: Settings,
    knowledge_base_id: str,
    content: bytes,
    *,
    file_name: str = "policy.md",
):
    service = DocumentService(connection, store, settings)
    upload = service.create_upload_url(
        _principal(),
        knowledge_base_id,
        UploadUrlRequest(
            fileName=file_name,
            mimeType="text/markdown",
            fileSizeBytes=len(content),
        ),
    )
    store.put(upload.objectKey, content, content_type="text/markdown")
    return service.complete_upload(
        _principal(),
        knowledge_base_id,
        CompleteUploadRequest(uploadSessionId=upload.uploadSessionId),
        request_id=f"complete-{upload.documentId}",
    )


@pytest.mark.asyncio
async def test_create_three_kbs_recreates_lost_outbox_and_provisions_unique_instances(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    with open_database_connection(settings) as connection:
        kbs = [_create_kb(connection, f"KB {index}") for index in range(1, 4)]
        # Simulate event loss after the source transaction. Startup reconciliation must recreate it.
        connection.execute(
            "delete from knowledge_index_outbox where knowledge_base_id = ?",
            (kbs[2].id,),
        )
        connection.commit()
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        worker.reconcile()
        await _drain_binding_events(worker, 3)

        bindings = LightragInstanceRepository(connection).bindings()
        assert len(bindings) == 3
        assert len({item.base_url for item in bindings}) == 3
        assert len({item.workspace for item in bindings}) == 3
        assert all(
            KnowledgeBaseRepository(connection).get(kb.id).indexStatus == "ready" for kb in kbs
        )
        # Restart can change an existing address as well as lose another container.
        original = provider.instances[kbs[0].id]
        provider.instances[kbs[0].id] = replace(original, base_url="http://172.20.0.42:9621")
        provider.instances.pop(kbs[2].id)
        await worker.reconcile_provider()
        assert KnowledgeBaseRepository(connection).get(kbs[2].id).indexStatus == "provisioning"
        await _drain_binding_events(worker, 3)
        assert kbs[2].id in provider.instances
        assert KnowledgeBaseRepository(connection).get(kbs[2].id).indexStatus == "ready"
        refreshed = LightragInstanceRepository(connection).require_binding(kbs[0].id)
        assert refreshed.base_url == "http://172.20.0.42:9621"
        assert (refreshed.provider_ref, refreshed.workspace) == (
            original.provider_ref, original.workspace
        )


@pytest.mark.asyncio
async def test_concurrent_kb_creation_and_document_uploads_keep_durable_unique_work(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)

    def create(index: int):
        with open_database_connection(settings) as connection:
            return _create_kb(connection, f"Concurrent {index}")

    kbs = await asyncio.gather(*(asyncio.to_thread(create, index) for index in range(4)))
    with open_database_connection(settings) as connection:
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 4)
        assert (
            len(
                {binding.workspace for binding in LightragInstanceRepository(connection).bindings()}
            )
            == 4
        )

    target_kb_id = kbs[0].id

    def upload(index: int):
        with open_database_connection(settings) as connection:
            return _upload(
                connection,
                LocalObjectStore(settings),
                settings,
                target_kb_id,
                f"parallel-{index}".encode(),
                file_name=f"parallel-{index}.md",
            )

    uploaded = await asyncio.gather(*(asyncio.to_thread(upload, index) for index in range(5)))

    with open_database_connection(settings) as connection:
        assert connection.execute(
            "select count(*) as count from knowledge_document_sync_jobs where operation = 'upsert'"
        ).fetchone()["count"] == len(uploaded)
        documents = DocumentRepository(connection).list_documents(target_kb_id)
        assert len(documents) == 5
        assert all(item.sourceSha and item.indexStatus == "pending" for item in documents)


@pytest.mark.asyncio
async def test_upload_auto_sync_retries_and_same_name_documents_stay_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    inserts: list[tuple[str, str]] = []
    attempts: dict[str, int] = {}
    deleted_index_ids: list[str] = []
    track_sources: dict[str, str] = {}

    async def convert(_self, _name: str, content: bytes) -> str:
        return content.decode("utf-8")

    async def insert(
        _self, _text: str, source: str, *, timeout: float, chunking: dict | None = None
    ) -> dict:
        assert timeout > 0
        assert chunking is not None
        attempts[source] = attempts.get(source, 0) + 1
        inserts.append((_self.base_url, source))
        if len(attempts) == 1 and attempts[source] == 1:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "temporary failure")
        track_id = f"track-{hashlib.sha256(source.encode()).hexdigest()[:12]}"
        track_sources[track_id] = source
        return {"track_id": track_id}

    async def track(_self, track_id: str) -> dict:
        return {
            "documents": [
                {"id": f"index-{track_id.removeprefix('track-')}", "status": "processed"}
                | {"file_path": track_sources[track_id]}
            ]
        }

    async def delete(_self, document_id: str) -> str:
        deleted_index_ids.append(document_id)
        return "not_found"

    async def find(_self, _source: str) -> None:
        return None

    monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert)
    monkeypatch.setattr(LightRagClient, "insert_text", insert)
    monkeypatch.setattr(LightRagClient, "track_status", track)
    monkeypatch.setattr(LightRagClient, "delete_document", delete)
    monkeypatch.setattr(LightRagClient, "find_document_by_file_source", find)
    monkeypatch.setattr(
        KnowledgeIndexWorker,
        "_retry_at",
        lambda _self, _attempt: "2000-01-01T00:00:00+00:00",
    )

    with open_database_connection(settings) as connection:
        kb_a = _create_kb(connection, "A")
        kb_b = _create_kb(connection, "B")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 2)
        doc_a = _upload(connection, store, settings, kb_a.id, b"alpha", file_name="policy.md")
        doc_b = _upload(connection, store, settings, kb_b.id, b"beta", file_name="policy.md")

        # Concurrent completion/reconciliation wake-ups collapse to one immutable-generation job.
        queue = KnowledgeIndexRepository(connection)
        queue.enqueue_document_upsert(
            kb_a.id,
            doc_a.id,
            doc_a.sourceSha,
            _now(),
            pipeline_version=settings.knowledge_index_pipeline_version,
        )
        queue.enqueue_document_upsert(
            kb_a.id,
            doc_a.id,
            doc_a.sourceSha,
            _now(),
            pipeline_version=settings.knowledge_index_pipeline_version,
        )
        connection.commit()
        assert (
            connection.execute(
                """
            select count(*) as count from knowledge_document_sync_jobs
            where document_id = ? and operation = 'upsert'
            """,
                (doc_a.id,),
            ).fetchone()["count"]
            == 1
        )

        for _ in range(3):
            assert await worker.poll_once()

        ready_a = DocumentRepository(connection).get_document(kb_a.id, doc_a.id)
        ready_b = DocumentRepository(connection).get_document(kb_b.id, doc_b.id)
        assert ready_a is not None and ready_a.indexedSha == ready_a.sourceSha
        assert ready_b is not None and ready_b.indexedSha == ready_b.sourceSha
        assert ready_a.indexDocumentId and ready_b.indexDocumentId
        assert ready_a.indexDocumentId != ready_b.indexDocumentId
        successful = {(url, source) for url, source in inserts}
        assert any(
            kb_a.id in source and url.endswith(kb_a.id + ":9621") for url, source in successful
        )
        assert any(
            kb_b.id in source and url.endswith(kb_b.id + ":9621") for url, source in successful
        )
        assert all("policy.md" not in source for _, source in successful)

        # Replacing the source keeps the old published generation available until the new one
        # succeeds, then cleans up only the superseded external generation.
        assert ready_a.sourceSha is not None
        old_sha = ready_a.sourceSha
        old_index_id = ready_a.indexDocumentId
        old_source = DocumentRepository(connection).get_citation_source(doc_a.id, old_sha)
        assert old_source is not None
        replacement_bytes = b"alpha replacement"
        service = DocumentService(connection, store, settings)
        replacement_upload = service.create_replacement_upload_url(
            _principal(),
            kb_a.id,
            doc_a.id,
            UploadUrlRequest(
                fileName="policy.md",
                mimeType="text/markdown",
                fileSizeBytes=len(replacement_bytes),
            ),
        )
        store.put(
            replacement_upload.objectKey,
            replacement_bytes,
            content_type="text/markdown",
        )
        with pytest.raises(ApiError, match="create or replacement endpoint") as mismatch:
            service.complete_upload(
                _principal(),
                kb_a.id,
                CompleteUploadRequest(uploadSessionId=replacement_upload.uploadSessionId),
                request_id="wrong-replacement-endpoint",
            )
        assert mismatch.value.code == "UPLOAD_SESSION_MODE_MISMATCH"
        replaced = service.complete_upload(
            _principal(),
            kb_a.id,
            CompleteUploadRequest(uploadSessionId=replacement_upload.uploadSessionId),
            request_id="replace-source",
            replacement_document_id=doc_a.id,
        )
        assert replaced.id == doc_a.id
        assert replaced.sourceSha != old_sha
        published_during_replacement = DocumentRepository(connection).list_retrieval_sources(
            kb_a.id
        )
        assert len(published_during_replacement) == 1
        assert published_during_replacement[0]["source_sha256"] == old_sha
        assert published_during_replacement[0]["index_document_id"] == old_index_id

        assert await worker.poll_once()
        refreshed = DocumentRepository(connection).get_document(kb_a.id, doc_a.id)
        assert refreshed is not None
        assert refreshed.sourceSha == hashlib.sha256(replacement_bytes).hexdigest()
        assert refreshed.indexedSha == refreshed.sourceSha
        assert old_index_id not in deleted_index_ids
        published_after_replacement = DocumentRepository(connection).list_retrieval_sources(kb_a.id)
        assert len(published_after_replacement) == 1
        assert published_after_replacement[0]["source_sha256"] == refreshed.sourceSha

        assert await worker.poll_once()
        assert old_index_id in deleted_index_ids
        assert DocumentRepository(connection).get_citation_source(doc_a.id, old_sha) == old_source
        untouched_b = DocumentRepository(connection).get_document(kb_b.id, doc_b.id)
        assert untouched_b is not None and untouched_b.sourceSha == ready_b.sourceSha


@pytest.mark.asyncio
async def test_delete_filters_immediately_then_async_cleanup_allows_gc(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    deleted_index_ids: list[str] = []

    monkeypatch.setattr(
        DoclingClient,
        "convert_to_markdown",
        lambda _self, _name, content: _async_value(content.decode()),
    )

    inserted_source = ""

    async def insert(
        _self, _text: str, _source: str, *, timeout: float, chunking: dict | None = None
    ) -> dict:
        nonlocal inserted_source
        inserted_source = _source
        return {"track_id": "track-delete"}

    async def track(_self, _track_id: str) -> dict:
        return {
            "documents": [
                {
                    "id": "index-delete",
                    "status": "processed",
                    "file_path": inserted_source,
                }
            ]
        }

    async def delete(_self, document_id: str) -> str:
        deleted_index_ids.append(document_id)
        return "not_found"

    async def find(_self, _source: str) -> None:
        return None

    monkeypatch.setattr(LightRagClient, "insert_text", insert)
    monkeypatch.setattr(LightRagClient, "track_status", track)
    monkeypatch.setattr(LightRagClient, "delete_document", delete)
    monkeypatch.setattr(LightRagClient, "find_document_by_file_source", find)

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Delete")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"delete me")
        assert await worker.poll_once()
        assert len(DocumentRepository(connection).list_retrieval_sources(kb.id)) == 1
        assert (
            len(
                DocumentRepository(connection).list_retrieval_sources(
                    kb.id, pipeline_version=settings.knowledge_index_pipeline_version
                )
            )
            == 1
        )
        assert (
            DocumentRepository(connection).list_retrieval_sources(
                kb.id, pipeline_version="different-pipeline"
            )
            == []
        )

        service = DocumentService(connection, store, settings)
        await service.delete_document(
            _principal(), kb.id, document.id, request_id="delete-document"
        )
        assert DocumentRepository(connection).list_retrieval_sources(kb.id) == []
        assert service.purge_deleted_objects() == 0

        assert await worker.poll_once()
        assert deleted_index_ids == ["index-delete"]
        assert service.purge_deleted_objects() == 1


@pytest.mark.asyncio
async def test_restart_requeues_processing_job_and_repairs_legacy_nullable_sha(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    provider = FakeProvider()
    content = b"legacy source"

    async def convert(_self, _name: str, raw: bytes) -> str:
        return raw.decode()

    inserted_source = ""

    async def insert(
        _self, _text: str, _source: str, *, timeout: float, chunking: dict | None = None
    ) -> dict:
        nonlocal inserted_source
        inserted_source = _source
        return {"track_id": "track-legacy"}

    async def track(_self, _track_id: str) -> dict:
        return {
            "documents": [
                {
                    "id": "index-legacy",
                    "status": "processed",
                    "file_path": inserted_source,
                }
            ]
        }

    async def find(_self, _source: str) -> None:
        return None

    monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert)
    monkeypatch.setattr(LightRagClient, "insert_text", insert)
    monkeypatch.setattr(LightRagClient, "track_status", track)
    monkeypatch.setattr(LightRagClient, "find_document_by_file_source", find)

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Legacy")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        source_key = f"knowledge-bases/{kb.id}/documents/doc_legacy/source.md"
        store.put(source_key, content, content_type="text/markdown")
        connection.execute(
            """
            insert into documents (
              id, knowledge_base_id, file_name, file_type, storage_key, object_bucket,
              content_hash, source_sha256, file_size_bytes, parse_status, index_status,
              created_by
            ) values (
              'doc_legacy', ?, 'legacy.md', 'md', ?, 'local', null, null, ?,
              'pending', 'pending', 'platform_admin'
            )
            """,
            (kb.id, source_key, len(content)),
        )
        connection.commit()
        worker.reconcile()
        connection.execute(
            """
            update knowledge_document_sync_jobs set status = 'processing', attempts = 3
            where document_id = 'doc_legacy'
            """
        )
        connection.commit()

        worker.repair_processing()
        repaired_job = connection.execute(
            "select status, attempts, completed_at from knowledge_document_sync_jobs "
            "where document_id = 'doc_legacy'"
        ).fetchone()
        assert dict(repaired_job) == {
            "status": "pending",
            "attempts": 3,
            "completed_at": None,
        }
        assert await worker.poll_once()
        repaired = DocumentRepository(connection).get_document(kb.id, "doc_legacy")
        assert repaired is not None
        assert repaired.sourceSha == hashlib.sha256(content).hexdigest()
        assert repaired.indexedSha == repaired.sourceSha
        assert (
            DocumentRepository(connection).get_citation_source(repaired.id, repaired.sourceSha)
            is not None
        )


@pytest.mark.asyncio
async def test_existing_processing_track_is_reused_without_second_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    insert_calls = 0

    async def insert(*_args, **_kwargs) -> dict:
        nonlocal insert_calls
        insert_calls += 1
        raise AssertionError("a persisted processing track must not be inserted again")

    async def convert(_self, _name: str, raw: bytes) -> str:
        return raw.decode()

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Track reuse")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"track reuse")
        file_source = f"kb-{kb.id}--doc-{document.id}--{document.sourceSha[:16]}.md"
        DocumentRepository(connection).set_lightrag_track_id(document.id, "track-existing", _now())
        connection.commit()

        async def track(_self, track_id: str) -> dict:
            assert track_id == "track-existing"
            return {
                "documents": [
                    {
                        "id": "index-existing",
                        "status": "processed",
                        "file_path": file_source,
                    }
                ]
            }

        monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert)
        monkeypatch.setattr(LightRagClient, "insert_text", insert)
        monkeypatch.setattr(LightRagClient, "track_status", track)

        assert await worker.poll_once()
        ready = DocumentRepository(connection).get_document(kb.id, document.id)
        assert ready is not None
        assert ready.parseStatus == "ready"
        assert ready.indexStatus == "ready"
        assert ready.indexDocumentId == "index-existing"
        assert ready.indexedSha == ready.sourceSha
        assert insert_calls == 0


@pytest.mark.asyncio
async def test_processing_track_is_deferred_so_other_jobs_can_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    polls = 0

    async def convert(_self, _name: str, raw: bytes) -> str:
        return raw.decode()

    async def track(_self, _track_id: str) -> dict:
        nonlocal polls
        polls += 1
        status = "processing" if polls == 1 else "processed"
        return {
            "documents": [
                {
                    "id": "index-deferred",
                    "status": status,
                    "file_path": file_source,
                }
            ]
        }

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Deferred track")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"deferred")
        file_source = f"kb-{kb.id}--doc-{document.id}--{document.sourceSha[:16]}.md"
        DocumentRepository(connection).set_lightrag_track_id(document.id, "track-deferred", _now())
        connection.commit()
        monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert)
        monkeypatch.setattr(LightRagClient, "track_status", track)

        assert await worker.poll_once()
        pending = connection.execute(
            "select status, attempts from knowledge_document_sync_jobs where document_id = ?",
            (document.id,),
        ).fetchone()
        assert dict(pending) == {"status": "pending", "attempts": 0}

        connection.execute(
            "update knowledge_document_sync_jobs set available_at = ? where document_id = ?",
            ("2000-01-01T00:00:00+00:00", document.id),
        )
        connection.commit()
        assert await worker.poll_once()
        ready = DocumentRepository(connection).get_document(kb.id, document.id)
        assert ready is not None and ready.indexStatus == "ready"
        assert polls == 2


@pytest.mark.asyncio
async def test_existing_processing_document_without_track_backs_off_without_delete_or_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    insert_calls = 0
    delete_calls = 0

    async def convert(_self, _name: str, raw: bytes) -> str:
        return raw.decode()

    async def find(_self, _source: str) -> dict:
        return {"id": "index-processing", "status": "processing"}

    async def insert(*_args, **_kwargs) -> dict:
        nonlocal insert_calls
        insert_calls += 1
        return {"track_id": "must-not-run"}

    async def delete(*_args, **_kwargs) -> str:
        nonlocal delete_calls
        delete_calls += 1
        return "not_found"

    monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert)
    monkeypatch.setattr(LightRagClient, "find_document_by_file_source", find)
    monkeypatch.setattr(LightRagClient, "insert_text", insert)
    monkeypatch.setattr(LightRagClient, "delete_document", delete)

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Processing conflict")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        document = _upload(connection, store, settings, kb.id, b"still processing")

        assert await worker.poll_once()
        job = connection.execute(
            "select status, last_error from knowledge_document_sync_jobs where document_id = ?",
            (document.id,),
        ).fetchone()
        assert job["status"] == "pending"
        assert "still processing" in job["last_error"]
        pending_document = DocumentRepository(connection).get_document(kb.id, document.id)
        assert pending_document is not None
        assert pending_document.indexStatus == "pending"
        assert "still processing" in str(pending_document.lastError)
        assert insert_calls == 0
        assert delete_calls == 0


@pytest.mark.asyncio
async def test_worker_marks_preexisting_duplicate_content_terminal_without_lightrag_insert(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    indexed_sources = _mock_successful_indexing(monkeypatch)

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Duplicate worker guard")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        original = _upload(connection, store, settings, kb.id, b"same source")

        duplicate_key = f"knowledge-bases/{kb.id}/documents/doc_duplicate/source.md"
        store.put(duplicate_key, b"same source", content_type="text/markdown")
        now = _now()
        duplicate = DocumentRepository(connection).create_document(
            document_id="doc_duplicate",
            knowledge_base_id=kb.id,
            file_name="copy.md",
            file_type="md",
            mime_type="text/markdown",
            storage_key=duplicate_key,
            object_bucket=store.bucket,
            content_hash=original.sourceSha,
            file_size_bytes=len(b"same source"),
            created_by=_principal().user_id,
            now=now,
        )
        KnowledgeIndexRepository(connection).enqueue_document_upsert(
            kb.id,
            duplicate.id,
            duplicate.sourceSha,
            now,
            pipeline_version=settings.knowledge_index_pipeline_version,
        )
        connection.commit()

        assert await worker.poll_once()
        assert DocumentRepository(connection).get_document(kb.id, original.id).indexStatus == "ready"
        assert await worker.poll_once()

        failed = DocumentRepository(connection).get_document(kb.id, duplicate.id)
        assert failed is not None
        assert failed.indexStatus == "failed"
        assert "same content" in str(failed.lastError)
        job = connection.execute(
            "select status, attempts from knowledge_document_sync_jobs where document_id = ?",
            (duplicate.id,),
        ).fetchone()
        assert dict(job) == {"status": "failed", "attempts": 1}
        assert len(indexed_sources) == 1


@pytest.mark.asyncio
async def test_worker_rejects_distinct_sources_with_identical_parsed_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    provider = FakeProvider()
    store = LocalObjectStore(settings)
    indexed_sources = _mock_successful_indexing(monkeypatch)

    async def convert_to_same_markdown(_self, _name: str, _raw: bytes) -> str:
        return "identical parsed markdown"

    monkeypatch.setattr(DoclingClient, "convert_to_markdown", convert_to_same_markdown)

    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Parsed duplicate worker guard")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        await _drain_binding_events(worker, 1)
        original = _upload(
            connection, store, settings, kb.id, b"source one", file_name="one.md"
        )
        duplicate = _upload(
            connection, store, settings, kb.id, b"source two", file_name="two.md"
        )

        assert await worker.poll_once()
        assert DocumentRepository(connection).get_document(kb.id, original.id).indexStatus == "ready"
        assert await worker.poll_once()

        failed = DocumentRepository(connection).get_document(kb.id, duplicate.id)
        assert failed is not None
        assert failed.parseStatus == "ready"
        assert failed.indexStatus == "failed"
        assert "same parsed content" in str(failed.lastError)
        assert len(indexed_sources) == 1


@pytest.mark.asyncio
async def test_capacity_failure_is_explicit_and_retryable(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "No capacity")
        worker = KnowledgeIndexWorker(connection, settings, store, provider=None)
        assert await worker.poll_once()
        failed = KnowledgeBaseRepository(connection).get(kb.id)
        assert failed is not None and failed.indexStatus == "failed"
        assert "No dynamic isolated LightRAG Controller" in str(failed.indexError)
        event = connection.execute(
            """
            select status, attempts, last_error from knowledge_index_outbox
            where knowledge_base_id = ? and event_type = 'binding.ensure'
            """,
            (kb.id,),
        ).fetchone()
        assert event["status"] == "pending"
        assert event["attempts"] == 1
        assert event["last_error"]

        recovered = KnowledgeIndexWorker(
            connection, settings, store, provider=FakeProvider()
        )
        recovered.reconcile()
        assert await recovered.poll_once()
        ready = KnowledgeBaseRepository(connection).get(kb.id)
        assert ready is not None and ready.indexStatus == "ready"


def test_reconcile_revives_docling_configuration_failure(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    configured = settings.model_copy(update={"docling_base_url": "http://docling"})
    _prepare(settings)
    store = LocalObjectStore(settings)
    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Docling recovery")
        document = _upload(connection, store, settings, kb.id, b"recover me")
        connection.execute(
            """
            update knowledge_document_sync_jobs
            set status = 'failed', attempts = 3,
                last_error = 'Docling service is not configured',
                available_at = '2999-01-01T00:00:00+00:00'
            where document_id = ? and operation = 'upsert'
            """,
            (document.id,),
        )
        connection.commit()

        KnowledgeIndexWorker(
            connection, configured, store, provider=FakeProvider()
        ).reconcile()

        job = connection.execute(
            """
            select status, attempts, last_error
            from knowledge_document_sync_jobs
            where document_id = ? and operation = 'upsert'
            """,
            (document.id,),
        ).fetchone()
        assert dict(job) == {"status": "pending", "attempts": 0, "last_error": None}


@pytest.mark.asyncio
async def test_dynamic_binding_is_not_released_when_controller_is_unavailable(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    _prepare(settings)
    store = LocalObjectStore(settings)
    provider = FakeProvider()
    with open_database_connection(settings) as connection:
        kb = _create_kb(connection, "Delete requires controller")
        provisioner = KnowledgeIndexWorker(connection, settings, store, provider=provider)
        assert await provisioner.poll_once()
        KnowledgeBaseService(connection).delete(
            _principal(), kb.id, request_id="delete-without-controller"
        )

        unavailable = KnowledgeIndexWorker(connection, settings, store, provider=None)
        assert await unavailable.poll_once()
        assert LightragInstanceRepository(connection).get_binding(kb.id) is not None
        event = connection.execute(
            """
            select status, last_error from knowledge_index_outbox
            where knowledge_base_id = ? and event_type = 'binding.delete'
            """,
            (kb.id,),
        ).fetchone()
        assert event["status"] == "pending"
        assert "without its Controller" in event["last_error"]


async def _async_value(value: str) -> str:
    return value


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

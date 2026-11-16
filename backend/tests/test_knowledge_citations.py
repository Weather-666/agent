from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import open_database_connection
from app.domain.chat import ChatTurn
from app.main import create_app
from app.services.chat_service import (
    ChatService,
    _match_retrieval_source,
    _public_retrieval_sources,
    _reference_chunks,
    _reference_locator,
    _sources_payload,
)
from app.services.object_store import LocalObjectStore


def _source(document_id: str, file_name: str, index_document_id: str = "") -> dict:
    return {
        "id": document_id,
        "knowledge_base_id": "kb_a",
        "build_id": "build_a",
        "file_name": file_name,
        "file_type": "pdf",
        "mime_type": "application/pdf",
        "storage_key": f"knowledge-bases/kb_a/documents/{document_id}/{file_name}",
        "content_hash": "a" * 64,
        "source_sha256": "a" * 64,
        "lightrag_file_source": (f"kb-kb_a--doc-{document_id}--{'a' * 16}.md"),
        "index_document_id": index_document_id or None,
    }


def test_reference_mapping_never_guesses_between_same_name_documents() -> None:
    first = _source("doc_first", "policy.pdf", "lightrag-first")
    second = _source("doc_second", "policy.pdf", "lightrag-second")

    assert (
        _match_retrieval_source(
            {"reference_id": "lightrag-first", "file_path": "policy.pdf"},
            [first, second],
        )
        == first
    )
    assert (
        _match_retrieval_source(
            {"file_path": "kb_a/doc_second/policy.pdf"},
            [first, second],
        )
        == second
    )
    assert (
        _match_retrieval_source(
            {"file_path": "doc_first--kbv_123.md"},
            [first, second],
        )
        == first
    )
    assert (
        _match_retrieval_source(
            {
                "reference_id": "1",
                "file_path": "kb-kb_a--doc-doc_first--aaaaaaaaaaaaaaaa.md",
            },
            [first, second],
        )
        == first
    )
    assert _match_retrieval_source({"file_path": "policy.pdf"}, [first, second]) is None
    assert _match_retrieval_source({"file_path": "policy.pdf"}, [first]) is None


def test_reference_content_and_locator_normalize_lightrag_shapes() -> None:
    content = [
        {
            "chunk_content": "<!-- expert-source-locator: page=2 -->\n First hit ",
            "page_number": 0,
            "chunk_id": "chunk-2",
        },
        "Second hit",
    ]
    assert _reference_chunks(content) == [
        "<!-- expert-source-locator: page=2 -->\n First hit",
        "Second hit",
    ]
    assert _reference_locator({"content": content}, "pdf") == {"type": "pdf"}
    assert _reference_locator({"content": content[:1]}, "pdf") == {
        "type": "pdf",
        "pageNumber": 2,
    }
    assert _reference_locator({"content": [{"text": "hit", "page_number": 0}]}, "pdf") == {
        "type": "pdf"
    }


def test_public_sources_are_readable_deduplicated_and_identifier_free() -> None:
    file_name = "产品手册 #1（最终）.pdf"
    references = [
        {
            "citationId": citation_id,
            "knowledgeBaseId": "kb_a",
            "knowledgeBaseName": "产品资料",
            "documentId": "doc_manual",
            "fileName": file_name,
            "filePath": "kb-kb_a--doc-doc_manual--aaaaaaaaaaaaaaaa.md",
            "sourceSha": "a" * 64,
            "sourceSha256": "a" * 64,
            "indexDocumentId": f"index-{index}",
            "referenceId": f"chunk-reference-{index}",
            "content": ["<!-- expert-source-locator: page=12 -->\nWarranty terms"],
            "hitText": "<!-- expert-source-locator: page=12 -->\nWarranty terms",
            "locator": {"type": "pdf", "pageNumber": 12, "chunkId": f"chunk-{index}"},
            "locatorProvenance": "docling-page-break",
            "previewUrl": f"/preview/{citation_id}",
            "downloadUrl": f"/download/{citation_id}",
        }
        for index, citation_id in enumerate(("cite_1", "cite_2"), start=1)
    ]

    public = _public_retrieval_sources(references)

    assert len(public) == 1
    assert public[0]["fileName"] == file_name
    assert "filePath" not in public[0]
    assert public[0]["pageNumber"] == 12
    assert public[0]["citationId"] == "cite_1"
    assert public[0]["citationIds"] == ["cite_1", "cite_2"]
    assert public[0]["hitText"] == "Warranty terms"
    serialized = json.dumps(public, ensure_ascii=False)
    for forbidden in (
        "sourceSha",
        "sourceSha256",
        "indexDocumentId",
        "referenceId",
        "chunkId",
        "aaaaaaaaaaaaaaaa",
    ):
        assert forbidden not in serialized


def test_public_sources_do_not_guess_missing_pages() -> None:
    pdf = {
        "citationId": "cite_pdf",
        "knowledgeBaseId": "kb_a",
        "documentId": "doc_pdf",
        "fileName": "manual.pdf",
        "content": ["No page marker"],
        "locator": {"type": "pdf", "pageNumber": 0},
    }
    text = {
        "citationId": "cite_text",
        "knowledgeBaseId": "kb_a",
        "documentId": "doc_text",
        "fileName": "notes.txt",
        "content": ["plain text"],
        "locator": {"type": "txt"},
    }

    public = _public_retrieval_sources([pdf, text, {**text, "citationId": "cite_text_2"}])

    assert public[0]["pageNumber"] is None
    assert public[0]["locator"] == {"type": "pdf"}
    assert public[1]["pageNumber"] is None
    assert public[1]["citationIds"] == ["cite_text", "cite_text_2"]


@pytest.mark.asyncio
async def test_history_does_not_guess_a_source_for_incomplete_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    turn = ChatTurn(
        id="turn_incomplete",
        sessionId="session_incomplete",
        requestText="question",
        responseText="answer",
        expertId="expert_1",
        runtimeType="codex",
        status="completed",
        retrievalRefs=[
            {
                "referenceId": "unknown-index-id",
                "filePath": "kb-secret--doc-secret--deadbeefdeadbeef.md",
                "content": ["Unmapped hit"],
            },
        ],
        createdAt="2026-09-01T00:00:00+00:00",
        completedAt="2026-09-01T00:00:01+00:00",
    )

    service = object.__new__(ChatService)
    service.connection = object()
    service.settings = Settings(_env_file=None)
    service.repo = SimpleNamespace(list_turns=lambda _session_id: [turn])
    monkeypatch.setattr(
        service,
        "_require_session",
        lambda *_args: {"expert_id": "expert_1"},
    )

    messages = await service.list_messages(SimpleNamespace(), "session_incomplete")
    references = messages[0]["retrievalRefs"]

    assert references == [{
        "citationId": None,
        "citationIds": [],
        "knowledgeBaseId": None,
        "knowledgeBaseName": None,
        "documentId": None,
        "fileName": "Source unavailable",
        "pageNumber": None,
        "mimeType": None,
        "hitText": None,
        "locator": {},
        "previewUrl": None,
        "downloadUrl": None,
        "available": False,
    }]
    assert "deadbeef" not in json.dumps(references)


@pytest.mark.asyncio
async def test_prepare_retrieval_enriches_each_kb_reference_and_requests_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict]] = []
    sources = {
        "kb_a": [_source("doc_a", "policy.pdf")],
        "kb_b": [
            {
                **_source("doc_b", "policy.pdf"),
                "knowledge_base_id": "kb_b",
                "build_id": "build_b",
            }
        ],
    }

    class FakeClient:
        def __init__(self, kb_id: str) -> None:
            self.kb_id = kb_id

        async def query_data(self, question: str, **kwargs) -> dict:
            calls.append((self.kb_id, kwargs))
            document_id = "doc_a" if self.kb_id == "kb_a" else "doc_b"
            marker = "OCR-A-ALPHA-84A1" if self.kb_id == "kb_a" else "OCR-B-BETA-93B2"
            return {
                "response": marker,
                "references": [
                    {
                        "reference_id": f"ref-{self.kb_id}",
                        "file_path": f"{self.kb_id}/{document_id}/policy.pdf",
                        "content": [
                            {
                                "text": (
                                    "<!-- expert-source-locator: page=1 -->\n" + marker
                                ),
                                "chunk_id": f"chunk-{self.kb_id}",
                            }
                        ],
                    }
                ],
            }

    class FakeDocuments:
        def __init__(self, _connection) -> None:
            pass

        def list_retrieval_sources(
            self, kb_id: str, *, pipeline_version: str | None = None
        ) -> list[dict]:
            assert pipeline_version == "docling-page-ocr-locator-v3"
            return sources[kb_id]

    class FakeKnowledgeBases:
        def __init__(self, _connection) -> None:
            pass

        def get(self, kb_id: str):
            return SimpleNamespace(name=f"Knowledge {kb_id}")

    class FakeInstances:
        def __init__(self, _connection) -> None:
            pass

        def map(self) -> dict[str, str]:
            return {}

    monkeypatch.setattr(
        "app.services.chat_service.client_for_kb",
        lambda _settings, kb_id, _instances: FakeClient(kb_id),
    )
    monkeypatch.setattr("app.services.chat_service.DocumentRepository", FakeDocuments)
    monkeypatch.setattr("app.services.chat_service.KnowledgeBaseRepository", FakeKnowledgeBases)
    monkeypatch.setattr("app.services.chat_service.LightragInstanceRepository", FakeInstances)

    service = object.__new__(ChatService)
    service.connection = object()
    service.settings = Settings(_env_file=None)
    service.repo = SimpleNamespace(
        knowledge_binding_states=lambda _expert_id: [
            {
                "knowledge_base_id": "kb_a",
                "knowledge_base_status": "active",
                "knowledge_base_deleted_at": None,
                "index_status": "ready",
                "binding_status": "ready",
                "base_url": "http://kb-a.test:9621",
                "workspace": "kb_a",
            },
            {
                "knowledge_base_id": "kb_b",
                "knowledge_base_status": "active",
                "knowledge_base_deleted_at": None,
                "index_status": "ready",
                "binding_status": "ready",
                "base_url": "http://kb-b.test:9621",
                "workspace": "kb_b",
            },
        ],
        list_kb_ids_for_expert=lambda _expert_id: ["kb_a", "kb_b"],
    )

    context, references, knowledge_scoped = await service.retrieve_expert_knowledge(
        "expert_1", "refund period", "turn_1"
    )

    assert [item["knowledgeBaseId"] for item in references] == ["kb_a", "kb_b"]
    assert [item["documentId"] for item in references] == ["doc_a", "doc_b"]
    assert [item["locator"]["pageNumber"] for item in references] == [1, 1]
    assert references[0]["previewUrl"].endswith("/cite_1/preview")
    assert references[1]["downloadUrl"].endswith("/cite_2/download")
    assert [item["sourceSha"] for item in references] == ["a" * 64, "a" * 64]
    assert all("sourceBuildId" not in item for item in references)
    assert "[cite_1]" in context and "[cite_2]" in context
    assert all(kwargs["chunk_top_k"] == 8 for _, kwargs in calls)
    assert knowledge_scoped is True

    payload = _sources_payload(references)
    assert [item["fileName"] for item in payload["documents"]] == [
        "policy.pdf",
        "policy.pdf",
    ]
    assert [item["pageNumber"] for item in payload["documents"]] == [1, 1]
    serialized = json.dumps(payload)
    assert "sourceSha" not in serialized
    assert "indexDocumentId" not in serialized
    assert "chunkId" not in serialized

    # The Expert relationship is unchanged, but the next Turn resolves the repository's new
    # byte-current generation. No Build/release/publication lookup participates in retrieval.
    sources["kb_a"] = [
        {
            **_source("doc_a", "policy.pdf", "index-doc-a-replaced"),
            "content_hash": "b" * 64,
            "source_sha256": "b" * 64,
            "lightrag_file_source": f"kb-kb_a--doc-doc_a--{'b' * 16}.md",
        }
    ]
    _updated_context, updated_references, _knowledge_scoped = (
        await service.retrieve_expert_knowledge(
            "expert_1", "refund period", "turn_2"
        )
    )
    assert updated_references[0]["documentId"] == "doc_a"
    assert updated_references[0]["sourceSha"] == "b" * 64
    assert updated_references[0]["indexDocumentId"] == "index-doc-a-replaced"


@pytest.mark.asyncio
async def test_prepare_retrieval_fails_closed_when_binding_is_not_ready() -> None:
    service = object.__new__(ChatService)
    service.connection = object()
    service.settings = Settings(_env_file=None)
    service.repo = SimpleNamespace(
        knowledge_binding_states=lambda _expert_id: [
            {
                "knowledge_base_id": "kb_a",
                "knowledge_base_status": "active",
                "knowledge_base_deleted_at": None,
                "index_status": "failed",
                "binding_status": "failed",
                "base_url": None,
                "workspace": None,
            }
        ],
        list_kb_ids_for_expert=lambda _expert_id: ["kb_a"],
    )

    with pytest.raises(ApiError) as raised:
        await service.retrieve_expert_knowledge("expert_1", "refund period", "turn_1")

    assert raised.value.status_code == 503
    assert raised.value.code == "KNOWLEDGE_INDEX_NOT_READY"
    assert raised.value.details == {
        "knowledgeBaseId": "kb_a",
        "indexStatus": "failed",
        "retryable": True,
    }


@pytest.mark.asyncio
async def test_prepare_retrieval_fails_closed_when_lightrag_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class UnavailableClient:
        async def query_data(self, *_args, **_kwargs) -> dict:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed")

    class FakeInstances:
        def __init__(self, _connection) -> None:
            pass

        def map(self) -> dict[str, str]:
            return {"kb_a": "http://lightrag-a.test:9621"}

    monkeypatch.setattr(
        "app.services.chat_service.client_for_kb",
        lambda *_args, **_kwargs: UnavailableClient(),
    )
    monkeypatch.setattr("app.services.chat_service.LightragInstanceRepository", FakeInstances)

    service = object.__new__(ChatService)
    service.connection = object()
    service.settings = Settings(_env_file=None)
    service.repo = SimpleNamespace(
        knowledge_binding_states=lambda _expert_id: [
            {
                "knowledge_base_id": "kb_a",
                "knowledge_base_status": "active",
                "knowledge_base_deleted_at": None,
                "index_status": "ready",
                "binding_status": "ready",
                "base_url": "http://kb-a.test:9621",
                "workspace": "kb_a",
            }
        ],
        list_kb_ids_for_expert=lambda _expert_id: ["kb_a"],
    )

    with pytest.raises(ApiError) as raised:
        await service.retrieve_expert_knowledge("expert_1", "refund period", "turn_1")

    assert raised.value.code == "LIGHTRAG_REQUEST_FAILED"
    assert raised.value.details == {"knowledgeBaseId": "kb_a"}


def test_turn_owner_can_preview_download_and_replay_citation(tmp_path: Path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'citations.sqlite3'}",
        default_tenant_id="tenant_default",
        jwt_secret="test-secret-with-at-least-32-bytes",
        object_storage_backend="local",
        object_storage_local_dir=str(tmp_path / "objects"),
    )
    app = create_app(settings)
    original = b"scanned-pdf-bytes"
    storage_key = "knowledge-bases/kb_citation/documents/doc_citation/policy.pdf"
    LocalObjectStore(settings).put(storage_key, original, content_type="application/pdf")

    with TestClient(app) as client:
        registered = client.post(
            "/api/v1/users/register",
            json={"email": "owner@example.com", "password": "secret123", "name": "Owner"},
        ).json()
        owner_id = registered["user"]["id"]
        citation = {
            "referenceId": "ref-1",
            "filePath": "policy.pdf",
            "content": ["<!-- expert-source-locator: page=1 -->\nOCR-A-ALPHA-84A1"],
            "citationId": "cite_1",
            "knowledgeBaseId": "kb_citation",
            "knowledgeBaseName": "Citation KB",
            "documentId": "doc_citation",
            "fileName": "policy.pdf",
            "sourceSha": hashlib.sha256(original).hexdigest(),
            "sourceSha256": hashlib.sha256(original).hexdigest(),
            "indexDocumentId": "lightrag-doc-citation",
            "mimeType": "application/pdf",
            "hitText": "OCR-A-ALPHA-84A1",
            "locator": {"type": "pdf", "pageNumber": 1},
            "locatorProvenance": "docling-page-break",
            "previewUrl": "/api/v1/chat/turns/turn_citation/citations/cite_1/preview",
            "downloadUrl": "/api/v1/chat/turns/turn_citation/citations/cite_1/download",
        }
        with open_database_connection(settings) as connection:
            owner_tenant_id = str(
                connection.execute(
                    "select tenant_id from tenant_members where user_id = ?",
                    (owner_id,),
                ).fetchone()["tenant_id"]
            )
            connection.execute(
                """
                insert into knowledge_bases (id, owner_user_id, name, status)
                values ('kb_citation', ?, 'Citation KB', 'active')
                """,
                (owner_id,),
            )
            connection.execute(
                """
                insert into documents (
                  id, knowledge_base_id, file_name, file_type, mime_type, storage_key,
                  object_bucket, source_sha256, indexed_sha256, index_document_id,
                  file_size_bytes, parse_status, index_status, created_by
                ) values (
                  'doc_citation', 'kb_citation', 'policy.pdf', 'pdf', 'application/pdf', ?,
                  'local', ?, ?, 'lightrag-doc-citation', ?, 'ready', 'ready', ?
                )
                """,
                (
                    storage_key,
                    hashlib.sha256(original).hexdigest(),
                    hashlib.sha256(original).hexdigest(),
                    len(original),
                    owner_id,
                ),
            )
            connection.execute(
                """
                insert into knowledge_document_source_versions (
                  document_id, source_sha256, knowledge_base_id, file_name, file_type,
                  mime_type, storage_key, object_bucket, file_size_bytes
                ) values (
                  'doc_citation', ?, 'kb_citation', 'policy.pdf', 'pdf',
                  'application/pdf', ?, 'local', ?
                )
                """,
                (hashlib.sha256(original).hexdigest(), storage_key, len(original)),
            )
            connection.execute(
                """
                insert into chat_sessions (id, tenant_id, user_id, title)
                values ('session_citation', ?, ?, 'Citation session')
                """,
                (owner_tenant_id, owner_id),
            )
            connection.execute(
                """
                insert into chat_turns (
                  id, session_id, tenant_id, user_id, request_text, response_text, status,
                  retrieval_refs, completed_at
                ) values (
                  'turn_citation', 'session_citation', ?, ?, 'question', 'answer',
                  'completed', ?, CURRENT_TIMESTAMP
                )
                """,
                (owner_tenant_id, owner_id, json.dumps([citation])),
            )
            connection.commit()

            headers = {
                "Authorization": f"Bearer {registered['accessToken']}",
                "x-tenant-id": owner_tenant_id,
            }

        preview = client.get(citation["previewUrl"], headers=headers)
        assert preview.status_code == 200, preview.text
        assert preview.json()["content"] == "OCR-A-ALPHA-84A1"
        assert preview.json()["locator"] == {"type": "pdf", "pageNumber": 1}
        assert preview.json()["pageNumber"] == 1
        assert "sourceSha" not in preview.json()
        assert "sourceSha256" not in preview.json()
        assert "indexDocumentId" not in preview.json()

        history = client.get(
            "/api/v1/chat/sessions/session_citation/messages",
            headers=headers,
        )
        assert history.status_code == 200, history.text
        public_reference = history.json()["items"][0]["retrievalRefs"][0]
        assert public_reference["fileName"] == "policy.pdf"
        assert "filePath" not in public_reference
        assert public_reference["pageNumber"] == 1
        for forbidden in (
            "sourceSha",
            "sourceSha256",
            "indexDocumentId",
            "referenceId",
            "chunkId",
        ):
            assert forbidden not in public_reference

        download = client.get(citation["downloadUrl"], headers=headers)
        assert download.status_code == 200, download.text
        downloaded = client.get(download.json()["downloadUrl"])
        assert downloaded.status_code == 200
        assert downloaded.content == original

        # Soft deletion invalidates retrieval immediately, while the exact immutable bytes remain
        # available to historical citations until object GC.
        with open_database_connection(settings) as connection:
            connection.execute(
                "update documents set deleted_at = CURRENT_TIMESTAMP where id = 'doc_citation'"
            )
        historical_download = client.get(citation["downloadUrl"], headers=headers)
        assert historical_download.status_code == 200, historical_download.text
        historical_bytes = client.get(historical_download.json()["downloadUrl"])
        assert historical_bytes.content == original

        replay = client.get("/api/v1/chat/turns/turn_citation/events", headers=headers)
        assert replay.status_code == 200
        assert "event: sources" in replay.text
        assert "OCR-A-ALPHA-84A1" in replay.text
        assert "lightrag-doc-citation" not in replay.text
        assert hashlib.sha256(original).hexdigest() not in replay.text

        other = client.post(
            "/api/v1/users/register",
            json={"email": "other@example.com", "password": "secret123", "name": "Other"},
        ).json()
        with open_database_connection(settings) as connection:
            other_tenant_id = str(
                connection.execute(
                    "select tenant_id from tenant_members where user_id = ?",
                    (other["user"]["id"],),
                ).fetchone()["tenant_id"]
            )
        other_headers = {
            "Authorization": f"Bearer {other['accessToken']}",
            "x-tenant-id": other_tenant_id,
        }
        assert client.get(citation["previewUrl"], headers=other_headers).status_code == 404
        assert client.get(citation["downloadUrl"], headers=other_headers).status_code == 404

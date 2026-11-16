from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import httpx

from app.core.config import Settings
from app.core.errors import ApiError


class LightRagClient:
    """Client for a single LightRAG server instance (documents + query API).

    All endpoints are authenticated by the X-API-Key header when LIGHTRAG_API_KEY is configured
    server-side. `file_source` doubles as the document unique key: callers must delete before
    re-inserting a same-name document (the server returns 409). Ingestion is asynchronous --
    insert returns a track_id that must be polled via track_status until the document reaches a
    terminal state (processed/failed).
    """

    def __init__(
        self,
        base_url: str,
        api_key: str | None,
        *,
        timeout: float = 60.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.transport = transport

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        return headers

    async def health(self) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=10.0,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.get("/health", headers=self._headers())
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("health response is not an object")
            return payload
        except ValueError as exc:
            raise ApiError(
                502,
                "LIGHTRAG_HEALTH_INVALID_RESPONSE",
                "LightRAG health response is invalid",
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(502, "LIGHTRAG_UNAVAILABLE", "LightRAG is unreachable") from exc

    async def validate_workspace(self, expected_workspace: str) -> dict[str, Any]:
        """Validate an assigned endpoint and reject an explicitly different workspace.

        The pinned LightRAG image exposes ``configuration.workspace``. Missing identity is an
        invalid response because endpoint uniqueness alone cannot prove KB isolation.
        """
        health = await self.health()
        configuration = health.get("configuration")
        actual = configuration.get("workspace") if isinstance(configuration, dict) else None
        if not isinstance(actual, str) or not actual.strip():
            raise ApiError(
                502,
                "LIGHTRAG_WORKSPACE_UNVERIFIED",
                "LightRAG health response does not identify its workspace",
                {"expectedWorkspace": expected_workspace},
            )
        if actual != expected_workspace:
            raise ApiError(
                409,
                "LIGHTRAG_WORKSPACE_MISMATCH",
                "LightRAG endpoint workspace does not match its knowledge-base binding",
                {"expectedWorkspace": expected_workspace, "actualWorkspace": actual},
            )
        return health

    async def clear_documents(self) -> None:
        """Remove the instance's complete document set before an in-place full rebuild.

        LightRAG acknowledges an exact clear with ``status=success``. Busy, partial and failed
        outcomes are terminal errors for the current build; the caller may retry the build later.
        """
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.request("DELETE", "/documents", headers=self._headers())
            if response.status_code == 409:
                raise ApiError(
                    409,
                    "LIGHTRAG_CLEAR_BUSY",
                    "LightRAG is busy and cannot clear documents",
                )
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError("clear response is not an object")
        except ApiError:
            raise
        except ValueError as exc:
            raise ApiError(
                502,
                "LIGHTRAG_CLEAR_INVALID_RESPONSE",
                "LightRAG clear response is invalid",
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(
                502,
                "LIGHTRAG_CLEAR_REQUEST_FAILED",
                "LightRAG document clear request failed",
            ) from exc

        status = str(payload.get("status") or "").strip().lower()
        if status == "success":
            return
        if status in {"busy", "processing", "running"}:
            raise ApiError(
                409,
                "LIGHTRAG_CLEAR_BUSY",
                "LightRAG is busy and cannot clear documents",
                {"status": status},
            )
        if status == "partial_success":
            raise ApiError(
                502,
                "LIGHTRAG_CLEAR_PARTIAL",
                "LightRAG cleared only part of the document set",
                {"status": status},
            )
        if status == "fail":
            raise ApiError(
                502,
                "LIGHTRAG_CLEAR_FAILED",
                "LightRAG failed to clear the document set",
                {"status": status},
            )
        raise ApiError(
            502,
            "LIGHTRAG_CLEAR_INVALID_RESPONSE",
            "LightRAG clear response did not report success",
            {"status": status},
        )

    async def insert_text(
        self,
        text: str,
        file_source: str,
        *,
        timeout: float | None = None,
        chunking: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"text": text, "file_source": file_source}
        if chunking is not None:
            payload["chunking"] = chunking
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=timeout or self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.post(
                    "/documents/text",
                    json=payload,
                    headers=self._headers(),
                )
            if response.status_code == 409:
                raise ApiError(
                    409,
                    "LIGHTRAG_DOCUMENT_CONFLICT",
                    "LightRAG already holds a document with this file_source",
                    {"fileSource": file_source},
                )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc

    async def track_status(self, track_id: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.get(
                    f"/documents/track_status/{track_id}", headers=self._headers()
                )
            if response.status_code == 404:
                raise ApiError(
                    404,
                    "LIGHTRAG_TRACK_NOT_FOUND",
                    "LightRAG ingestion track no longer exists",
                    {"trackId": track_id},
                )
            response.raise_for_status()
            return response.json()
        except ApiError:
            raise
        except httpx.HTTPError as exc:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc

    async def delete_document(self, doc_id: str) -> str:
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                # httpx's delete() convenience method takes no body; request() does.
                response = await client.request(
                    "DELETE",
                    "/documents/delete_document",
                    json={"doc_ids": [doc_id]},
                    headers=self._headers(),
                )
            if response.status_code == 404:
                return "not_found"
            response.raise_for_status()
            payload = response.json()
            status = str((payload or {}).get("status") or "").strip().lower()
            if status == "busy":
                raise ApiError(
                    409,
                    "LIGHTRAG_DELETE_BUSY",
                    "LightRAG is busy and cannot delete the document yet",
                    {"documentId": doc_id, "retryable": True},
                )
            if status == "not_allowed":
                raise ApiError(
                    409,
                    "LIGHTRAG_DELETE_NOT_ALLOWED",
                    "LightRAG rejected document deletion",
                    {"documentId": doc_id, "retryable": True},
                )
            if status != "deletion_started":
                raise ApiError(
                    502,
                    "LIGHTRAG_DELETE_INVALID_RESPONSE",
                    "LightRAG document deletion returned an invalid status",
                    {"documentId": doc_id, "status": status},
                )
            return status
        except ApiError:
            raise
        except ValueError as exc:
            raise ApiError(
                502,
                "LIGHTRAG_DELETE_INVALID_RESPONSE",
                "LightRAG document deletion returned invalid JSON",
                {"documentId": doc_id},
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc

    async def find_document_by_file_source(
        self, file_source: str, *, max_pages: int = 10
    ) -> dict[str, Any] | None:
        """Resolve a document id by file_path via the paginated listing.

        Used by the 409 self-heal when neither the doc id nor the ingestion track id is known.
        The listing is unbounded on large indexes, so the search is page-capped.
        """
        for page in range(1, max_pages + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout,
                    transport=self.transport,
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        "/documents/paginated",
                        json={"page": page, "page_size": 100},
                        headers=self._headers(),
                    )
                response.raise_for_status()
                documents = (response.json() or {}).get("documents") or []
            except httpx.HTTPError as exc:
                raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc
            if not documents:
                return None
            # LightRAG canonicalizes file sources down to their basename, so both the full
            # source and its basename must match.
            basename = file_source.rsplit("/", 1)[-1]
            for document in documents:
                stored = str(document.get("file_path") or "")
                if stored in (file_source, basename):
                    return document
        return None

    async def find_doc_id_by_file_source(
        self, file_source: str, *, max_pages: int = 10
    ) -> str | None:
        document = await self.find_document_by_file_source(file_source, max_pages=max_pages)
        if document is None:
            return None
        return str(document.get("id") or "") or None

    async def document_exists(self, doc_id: str, *, max_pages: int = 10) -> bool:
        for page in range(1, max_pages + 1):
            try:
                async with httpx.AsyncClient(
                    base_url=self.base_url,
                    timeout=self.timeout,
                    transport=self.transport,
                    trust_env=False,
                ) as client:
                    response = await client.post(
                        "/documents/paginated",
                        json={"page": page, "page_size": 100},
                        headers=self._headers(),
                    )
                response.raise_for_status()
                documents = (response.json() or {}).get("documents") or []
            except httpx.HTTPError as exc:
                raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc
            if any(str(item.get("id") or "") == doc_id for item in documents):
                return True
            if not documents:
                return False
        return False

    async def wait_document_deleted(
        self,
        doc_id: str,
        *,
        timeout: float,
        poll_initial: float,
        poll_max: float,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + timeout
        delay = poll_initial
        while asyncio.get_running_loop().time() < deadline:
            if not await self.document_exists(doc_id):
                return
            await asyncio.sleep(delay)
            delay = min(poll_max, delay * 1.5)
        raise ApiError(
            409,
            "LIGHTRAG_DELETE_TIMEOUT",
            "LightRAG did not finish deleting the document within the configured timeout",
            {"documentId": doc_id, "retryable": True},
        )

    async def query(
        self,
        question: str,
        *,
        mode: str = "hybrid",
        top_k: int = 20,
        only_need_context: bool = True,
        include_references: bool = True,
        include_chunk_content: bool = False,
        conversation_history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "query": question,
            "mode": mode,
            "top_k": top_k,
            "only_need_context": only_need_context,
            "include_references": include_references,
            "include_chunk_content": include_chunk_content,
        }
        if conversation_history:
            payload["conversation_history"] = conversation_history
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.post("/query", json=payload, headers=self._headers())
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc

    async def query_data(
        self,
        question: str,
        *,
        mode: str = "hybrid",
        top_k: int = 10,
        chunk_top_k: int = 8,
        enable_rerank: bool = False,
    ) -> dict[str, Any]:
        """Return exact retrieved chunks without LightRAG-generated answer text.

        `/query/data` preserves each chunk id and file path. Backend can therefore build model
        context exclusively from citation-mapped chunks instead of mixing in graph prose that
        cannot be tied to one source.
        """
        payload = {
            "query": question,
            "mode": mode,
            "top_k": top_k,
            "chunk_top_k": chunk_top_k,
            "enable_rerank": enable_rerank,
            "include_references": True,
        }
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                response = await client.post("/query/data", json=payload, headers=self._headers())
            response.raise_for_status()
            body = response.json()
        except (ValueError, TypeError) as exc:
            raise ApiError(
                502,
                "LIGHTRAG_QUERY_INVALID_RESPONSE",
                "LightRAG query data response is invalid",
            ) from exc
        except httpx.TimeoutException as exc:
            raise ApiError(
                504,
                "KNOWLEDGE_RETRIEVAL_TIMEOUT",
                "Knowledge retrieval exceeded its deadline",
                {"retryable": True},
            ) from exc
        except httpx.HTTPError as exc:
            raise ApiError(502, "LIGHTRAG_REQUEST_FAILED", "LightRAG request failed") from exc
        data = body.get("data") if isinstance(body, dict) else None
        metadata = body.get("metadata") if isinstance(body, dict) else None
        if (
            isinstance(data, dict)
            and not data
            and isinstance(metadata, dict)
            and metadata.get("failure_reason") == "no_results"
        ):
            return {"references": [], "metadata": metadata}
        chunks = data.get("chunks") if isinstance(data, dict) else None
        if not isinstance(chunks, list) or any(not isinstance(item, dict) for item in chunks):
            raise ApiError(
                502,
                "LIGHTRAG_QUERY_INVALID_RESPONSE",
                "LightRAG query data response omitted retrieved chunks",
            )
        grouped: dict[tuple[str, str], dict[str, Any]] = {}
        for chunk in chunks:
            reference_id = str(chunk.get("reference_id") or "")
            file_path = str(chunk.get("file_path") or "")
            content = chunk.get("content")
            if (
                not reference_id
                or not file_path
                or not isinstance(content, str)
                or not content.strip()
            ):
                continue
            key = (reference_id, file_path)
            reference = grouped.setdefault(
                key,
                {
                    "reference_id": reference_id,
                    "file_path": file_path,
                    "content": [],
                },
            )
            reference["content"].append(
                {
                    "content": content,
                    "chunk_id": str(chunk.get("chunk_id") or ""),
                }
            )
        return {
            "references": list(grouped.values()),
            "metadata": metadata if isinstance(metadata, dict) else {},
        }


def client_for_kb(
    settings: Settings,
    knowledge_base_id: str,
    instances: Mapping[str, str] | None = None,
) -> LightRagClient:
    """Pick the LightRAG instance serving a knowledge base.

    `instances` is the persisted kb_id -> base_url binding registry. There is deliberately no
    global fallback: an unassigned knowledge base must never enter another base's shared index.
    """
    base_url = (instances or {}).get(knowledge_base_id)
    if not base_url:
        raise ApiError(
            503,
            "LIGHTRAG_INSTANCE_NOT_ASSIGNED",
            "Knowledge base has no isolated LightRAG instance",
            {"knowledgeBaseId": knowledge_base_id},
        )
    return LightRagClient(
        base_url,
        settings.lightrag_api_key,
        timeout=settings.lightrag_timeout_seconds,
    )

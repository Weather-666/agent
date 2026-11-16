#!/usr/bin/env python3
"""Real disposable KB -> Controller -> Docling -> LightRAG automatic-sync acceptance."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

import httpx

from app.clients.lightrag_client import LightRagClient
from app.core.config import get_settings
from app.db import open_database_connection
from app.services._sql import fetch_one
from app.services.document_repository import DocumentRepository
from app.services.lightrag_instance_repository import LightragInstanceRepository


@dataclass
class Resources:
    knowledge_bases: list[str] = field(default_factory=list)
    documents: list[tuple[str, str]] = field(default_factory=list)


class Acceptance:
    def __init__(self) -> None:
        self.base_url = os.getenv("KB_AUTO_E2E_BASE_URL", "http://127.0.0.1:15000")
        self.email = os.getenv("KB_AUTO_E2E_ADMIN_EMAIL", "e2e-admin@example.com")
        self.password = os.getenv("KB_AUTO_E2E_ADMIN_PASSWORD", "e2e-password")
        self.client = httpx.Client(base_url=self.base_url, timeout=60)
        self.headers: dict[str, str] = {}
        self.refresh_token = ""
        self.access_expires_at = 0.0
        self.resources = Resources()

    def run(self) -> None:
        self._authenticate()
        tag = uuid4().hex[:10]
        for index in range(3):
            kb = self._json(
                "POST",
                "/api/v1/knowledge-bases",
                headers=self.headers,
                json={"name": f"kb-auto-e2e-{tag}-{index}"},
                expected=201,
            )
            self.resources.knowledge_bases.append(str(kb["id"]))
        self._wait_kbs_ready()
        self._assert_unique_bindings()

        specs = (
            (self.resources.knowledge_bases[0], "AUTOSYNC ALPHA 8472"),
            (self.resources.knowledge_bases[1], "AUTOSYNC BETA 9316"),
        )
        for kb_id, marker in specs:
            content = f"# Isolated policy\n\nThe exact approval code is {marker}.\n".encode()
            document = self._upload(kb_id, "same-policy.md", content)
            self.resources.documents.append((kb_id, str(document["id"])))
        ready = [self._wait_document(kb_id, doc_id) for kb_id, doc_id in self.resources.documents]
        assert all(item["sourceSha"] == item["indexedSha"] for item in ready)
        assert len({item["indexDocumentId"] for item in ready}) == 2

        asyncio.run(self._assert_isolated_queries(specs))

        # Replace the first source in place. No Build or Expert publication is involved: the old
        # published generation stays queryable until the new immutable generation is ready.
        kb_id, document_id = self.resources.documents[0]
        old_ready = ready[0]
        old_sha = str(old_ready["sourceSha"])
        replacement_marker = "AUTOSYNC ALPHA REPLACED 6641"
        replacement_body = (
            f"# Isolated replacement\n\nThe exact approval code is {replacement_marker}.\n"
        ).encode()
        replaced = self._replace(kb_id, document_id, "same-policy.md", replacement_body)
        assert replaced["id"] == document_id
        assert replaced["sourceSha"] != old_sha
        with open_database_connection(get_settings()) as connection:
            repository = DocumentRepository(connection)
            published = repository.list_retrieval_sources(kb_id)
            assert len(published) == 1
            assert published[0]["source_sha256"] == old_sha
            assert repository.get_citation_source(document_id, old_sha) is not None
        replacement_ready = self._wait_document(kb_id, document_id)
        assert replacement_ready["sourceSha"] == replacement_ready["indexedSha"]
        assert replacement_ready["indexDocumentId"] != old_ready["indexDocumentId"]
        replaced_specs = (
            (kb_id, replacement_marker),
            specs[1],
        )
        asyncio.run(self._assert_isolated_queries(replaced_specs, forbidden={kb_id: specs[0][1]}))

        response = self._request(
            "DELETE",
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document_id}",
            headers=self.headers,
        )
        assert response.status_code == 204, response.text
        with open_database_connection(get_settings()) as connection:
            assert DocumentRepository(connection).list_retrieval_sources(kb_id) == []
        print(
            {
                "result": "KB_AUTO_SYNC_E2E_OK",
                "knowledgeBases": len(self.resources.knowledge_bases),
                "sameNameDocuments": 2,
                "sourceIndexedShaMatched": True,
                "sourceReplacedWithoutBuild": True,
                "historicalCitationSourceRetained": True,
                "deleteFilteredImmediately": True,
            }
        )

    def cleanup(self) -> None:
        for kb_id in reversed(self.resources.knowledge_bases):
            self._request("DELETE", f"/api/v1/knowledge-bases/{kb_id}", headers=self.headers)
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            self._request("POST", "/api/v1/ops/storage/gc", headers=self.headers, json={})
            with open_database_connection(get_settings()) as connection:
                remaining = connection.execute(
                    "select count(*) as count from knowledge_bases"
                ).fetchone()["count"]
            if int(remaining) == 0:
                return
            time.sleep(1)
        raise RuntimeError("disposable KB cleanup did not reach zero source rows")

    def close(self) -> None:
        self.client.close()

    def _wait_kbs_ready(self) -> None:
        for kb_id in self.resources.knowledge_bases:
            deadline = time.monotonic() + 240
            while time.monotonic() < deadline:
                kb = self._json("GET", f"/api/v1/knowledge-bases/{kb_id}", headers=self.headers)
                if kb["indexStatus"] == "ready":
                    break
                if kb["indexStatus"] == "failed":
                    raise RuntimeError(kb.get("indexError") or "provisioning failed")
                time.sleep(1)
            else:
                raise TimeoutError(f"KB {kb_id} did not become ready")

    def _assert_unique_bindings(self) -> None:
        with open_database_connection(get_settings()) as connection:
            bindings = LightragInstanceRepository(connection).bindings()
        assert len(bindings) == 3
        assert len({item.base_url for item in bindings}) == 3
        assert len({item.workspace for item in bindings}) == 3

    def _upload(self, kb_id: str, file_name: str, content: bytes) -> dict:
        upload = self._json(
            "POST",
            f"/api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            headers=self.headers,
            json={
                "fileName": file_name,
                "mimeType": "text/markdown",
                "fileSizeBytes": len(content),
            },
        )
        put_url, put_headers = self._upload_request(upload)
        put = self.client.put(put_url, content=content, headers=put_headers)
        assert put.status_code in {200, 201, 204}, put.text
        return self._json(
            "POST",
            f"/api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            headers=self.headers,
            json={"uploadSessionId": upload["uploadSessionId"]},
            expected=201,
        )

    def _replace(self, kb_id: str, document_id: str, file_name: str, content: bytes) -> dict:
        upload = self._json(
            "POST",
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document_id}/upload-url",
            headers=self.headers,
            json={
                "fileName": file_name,
                "mimeType": "text/markdown",
                "fileSizeBytes": len(content),
            },
        )
        put_url, put_headers = self._upload_request(upload)
        put = self.client.put(put_url, content=content, headers=put_headers)
        assert put.status_code in {200, 201, 204}, put.text
        return self._json(
            "POST",
            f"/api/v1/knowledge-bases/{kb_id}/docs/{document_id}/complete-upload",
            headers=self.headers,
            json={"uploadSessionId": upload["uploadSessionId"]},
        )

    def _wait_document(self, kb_id: str, document_id: str) -> dict:
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            document = self._json(
                "GET",
                f"/api/v1/knowledge-bases/{kb_id}/docs/{document_id}",
                headers=self.headers,
            )
            if document["indexStatus"] == "ready":
                return document
            if document["indexStatus"] == "failed":
                # External failures are represented on the Document immediately but the durable
                # job remains pending with bounded backoff. Fail only when no retryable job owns
                # this current generation.
                with open_database_connection(get_settings()) as connection:
                    job = fetch_one(
                        connection,
                        """
                        select status from knowledge_document_sync_jobs
                        where document_id = ? and operation = 'upsert'
                        order by created_at desc limit 1
                        """,
                        (document_id,),
                    )
                if job is None or str(job["status"]) not in {"pending", "processing"}:
                    raise RuntimeError(document.get("lastError") or document.get("parseError"))
            time.sleep(2)
        raise TimeoutError(f"Document {document_id} did not become ready")

    @staticmethod
    def _upload_request(upload: dict) -> tuple[str, dict[str, str]]:
        """Connect through an internal MinIO origin while preserving the signed public Host."""
        upload_url = str(upload["uploadUrl"])
        headers = dict(upload.get("headers") or {})
        connect_base = os.getenv("KB_AUTO_E2E_UPLOAD_CONNECT_BASE_URL", "").strip()
        if not connect_base:
            return upload_url, headers
        signed = urlsplit(upload_url)
        connect = urlsplit(connect_base)
        if connect.scheme not in {"http", "https"} or not connect.netloc:
            raise RuntimeError("KB_AUTO_E2E_UPLOAD_CONNECT_BASE_URL must be an HTTP(S) origin")
        headers["Host"] = signed.netloc
        return (
            urlunsplit((connect.scheme, connect.netloc, signed.path, signed.query, signed.fragment)),
            headers,
        )

    async def _assert_isolated_queries(
        self,
        specs: tuple[tuple[str, str], ...],
        *,
        forbidden: dict[str, str] | None = None,
    ) -> None:
        settings = get_settings()
        with open_database_connection(settings) as connection:
            bindings = {
                item.knowledge_base_id: item
                for item in LightragInstanceRepository(connection).bindings()
            }
        for kb_id, marker in specs:
            other = next(item for other_kb, item in specs if other_kb != kb_id)
            result = await LightRagClient(
                bindings[kb_id].base_url,
                settings.lightrag_api_key,
                timeout=120,
            ).query(
                f"What exact approval code contains {marker.split()[1]}?",
                mode="hybrid",
                top_k=10,
                only_need_context=True,
                include_references=True,
                include_chunk_content=True,
            )
            serialized = str(result)
            assert marker in serialized
            assert other not in serialized
            if forbidden and kb_id in forbidden:
                assert forbidden[kb_id] not in serialized

    def _json(self, method: str, path: str, *, expected: int = 200, **kwargs) -> dict:
        response = self._request(method, path, **kwargs)
        assert response.status_code == expected, (response.status_code, response.text)
        body = response.json()
        assert isinstance(body, dict)
        return body

    def _authenticate(self) -> None:
        response = self.client.post(
            "/api/v1/auth/login",
            json={"email": self.email, "password": self.password},
        )
        assert response.status_code == 200, (response.status_code, response.text)
        payload = response.json()
        token = str(payload["accessToken"])
        self.refresh_token = str(payload["refreshToken"])
        self.access_expires_at = time.monotonic() + float(payload["expiresInSeconds"])
        # Mutate in place: retry kwargs may already reference this dict.
        self.headers.clear()
        self.headers["Authorization"] = f"Bearer {token}"

    def _refresh(self) -> None:
        response = self.client.post(
            "/api/v1/auth/refresh",
            json={"refreshToken": self.refresh_token},
        )
        assert response.status_code == 200, (response.status_code, response.text)
        payload = response.json()
        self.refresh_token = str(payload["refreshToken"])
        self.access_expires_at = time.monotonic() + float(payload["expiresInSeconds"])
        self.headers["Authorization"] = f"Bearer {payload['accessToken']}"

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if path not in {"/api/v1/auth/login", "/api/v1/auth/refresh"}:
            if self.refresh_token and time.monotonic() >= self.access_expires_at - 60:
                self._refresh()
        response = self.client.request(method, path, **kwargs)
        if response.status_code != 401 or path == "/api/v1/auth/login":
            return response
        self._refresh()
        return self.client.request(method, path, **kwargs)


def main() -> None:
    acceptance = Acceptance()
    try:
        acceptance.run()
    finally:
        try:
            acceptance.cleanup()
        finally:
            acceptance.close()


if __name__ == "__main__":
    main()

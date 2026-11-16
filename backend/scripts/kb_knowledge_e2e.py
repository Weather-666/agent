"""Run a destructive, real-service knowledge lifecycle acceptance.

This script creates only disposable resources with a ``kb-e2e-`` prefix. It drives the public
Backend API, performs the presigned object-store PUT, waits for automatic indexing, publishes two
Experts, and consumes the real chat SSE stream. The generated PDFs are image-only and share the
exact same filename, so a green run proves OCR and KB provenance instead of searchable PDF text or
filename guessing.

Run it from a network namespace that can reach both Backend and the upload URL returned by
Backend. In the Docker stack that normally means the Backend container::

    uv run python scripts/kb_knowledge_e2e.py \
      --base-url http://backend:8000 \
      --admin-email admin@example.com \
      --tenant-email user@example.com \
      --tenant-id tenant_x \
      --category-id expert_cat_ops

Passwords are read from ``KB_E2E_ADMIN_PASSWORD`` and ``KB_E2E_TENANT_PASSWORD`` by default.
The tenant's active Plan must include newly published Experts. Use ``--keep-resources`` only when
you need the generated Experts, Sessions and KBs for manual diagnosis after a failure.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageDraw, ImageFont


SAME_FILE_NAME = "scanned-policy.pdf"


@dataclass(frozen=True)
class VersionSpec:
    label: str
    marker: str
    fact: str

    @property
    def question(self) -> str:
        return "What is the exact approval code in the scanned policy?"


@dataclass
class TurnResult:
    turn_id: str = ""
    answer: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)
    raw_events: list[tuple[str, dict[str, Any]]] = field(default_factory=list)


@dataclass
class Resources:
    knowledge_bases: list[str] = field(default_factory=list)
    documents: list[tuple[str, str]] = field(default_factory=list)
    experts: list[str] = field(default_factory=list)
    sessions: list[str] = field(default_factory=list)


class Acceptance:
    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args
        self.base_url = args.base_url.rstrip("/") + "/"
        self.client = httpx.Client(timeout=httpx.Timeout(args.http_timeout))
        self.platform_headers: dict[str, str] = {}
        self.tenant_headers: dict[str, str] = {}
        self.platform_refresh_token = ""
        self.tenant_refresh_token = ""
        self.platform_access_expires_at = 0.0
        self.tenant_access_expires_at = 0.0
        self.resources = Resources()
        self.plan_id: str | None = None
        self.original_plan_expert_ids: list[str] = []
        self.plan_modified = False
        self.unlisted_expert_ids: set[str] = set()

    def close(self) -> None:
        self.client.close()

    def run(self) -> None:
        run_tag = str(int(time.time()))
        specs = {
            "a1": VersionSpec("KB A version 1", "ALPHA84A1", "Approval code ALPHA84A1"),
            "b1": VersionSpec("KB B version 1", "BETA93B2", "Approval code BETA93B2"),
        }

        self._login()
        print("[1/6] create two isolated knowledge bases")
        kb_a = self._create_kb(f"kb-e2e-a-{run_tag}")
        kb_b = self._create_kb(f"kb-e2e-b-{run_tag}")

        print("[2/6] upload two image-only PDFs with the same filename")
        doc_a1, pdf_a1 = self._upload_scanned_pdf(kb_a, specs["a1"])
        doc_b1, pdf_b1 = self._upload_scanned_pdf(kb_b, specs["b1"])
        assert pdf_a1 != pdf_b1

        print("[3/6] wait for automatic indexing and isolated readiness")
        ready_a1 = self._wait_document(kb_a, doc_a1)
        ready_b1 = self._wait_document(kb_b, doc_b1)
        assert ready_a1["sourceSha"] == ready_a1["indexedSha"]
        assert ready_b1["sourceSha"] == ready_b1["indexedSha"]
        assert ready_a1["indexDocumentId"] != ready_b1["indexDocumentId"]

        print("[4/6] publish one disposable Expert per KB")
        expert_a = self._create_and_publish_expert(kb_a, "A", run_tag)
        expert_b = self._create_and_publish_expert(kb_b, "B", run_tag)
        self._grant_plan_access([expert_a, expert_b])

        print("[5/6] retrieve/chat/cite both KBs and prove same-name isolation")
        turn_a1 = self._chat_and_assert(
            expert_a,
            kb_a,
            doc_a1,
            specs["a1"],
            forbidden=[specs["b1"].marker],
        )
        turn_b1 = self._chat_and_assert(
            expert_b,
            kb_b,
            doc_b1,
            specs["b1"],
            forbidden=[specs["a1"].marker],
        )
        self._assert_citation_io(turn_a1, pdf_a1, specs["a1"])
        self._assert_citation_io(turn_b1, pdf_b1, specs["b1"])
        self._assert_replay_sources(turn_a1)
        self._assert_replay_sources(turn_b1)

        print("[6/6] verify durable citations, then remove source and publication resources")
        self._delete_document(kb_a, doc_a1)
        self._assert_citation_survives_delete(turn_a1, pdf_a1, specs["a1"])
        self._delete_document(kb_b, doc_b1)
        self._assert_citation_survives_delete(turn_b1, pdf_b1, specs["b1"])
        self._unlist_expert(expert_a)
        self._unlist_expert(expert_b)
        self._delete_kb(kb_a)
        self._delete_kb(kb_b)
        self._assert_kb_deleted(kb_a)
        self._assert_kb_deleted(kb_b)
        purged_knowledge_bases = 0
        gc_deadline = time.monotonic() + 120
        while time.monotonic() < gc_deadline:
            gc_result = self._json(
                "POST", "api/v1/ops/storage/gc", self.platform_headers, json_body={}
            )
            purged_knowledge_bases += int(gc_result.get("purgedKnowledgeBases") or 0)
            if purged_knowledge_bases >= 2:
                break
            time.sleep(self.args.poll_interval)
        assert purged_knowledge_bases >= 2, {
            "purgedKnowledgeBases": purged_knowledge_bases,
            "lastGcResult": gc_result,
        }
        print("PASS: real OCR, automatic isolated retrieval, citations and delete were verified")

    def cleanup(self) -> None:
        self._restore_plan_access()
        if self.args.keep_resources:
            print("Resources retained:", json.dumps(self.resources.__dict__, ensure_ascii=False))
            return
        for session_id in reversed(self.resources.sessions):
            self._best_effort("DELETE", f"api/v1/chat/sessions/{session_id}", self.tenant_headers)
        for expert_id in reversed(self.resources.experts):
            if expert_id not in self.unlisted_expert_ids:
                self._best_effort(
                    "PATCH",
                    f"api/v1/experts/{expert_id}/status",
                    self.platform_headers,
                    json_body={"status": "unlisted"},
                )
            self._best_effort("DELETE", f"api/v1/experts/{expert_id}", self.platform_headers)
        for kb_id in reversed(self.resources.knowledge_bases):
            self._best_effort("DELETE", f"api/v1/knowledge-bases/{kb_id}", self.platform_headers)
        # A failed run can stop before phase 6's explicit GC. Soft deletion alone intentionally
        # keeps the exclusive LightRAG lease, so make one final best-effort purge after Sessions
        # and Experts have been removed.
        self._best_effort("POST", "api/v1/ops/storage/gc", self.platform_headers, json_body={})

    def _login(self) -> None:
        admin_password = _required_secret(self.args.admin_password_env)
        tenant_password = _required_secret(self.args.tenant_password_env)
        admin = self._json(
            "POST",
            "api/v1/auth/login",
            json_body={"email": self.args.admin_email, "password": admin_password},
        )
        tenant = self._json(
            "POST",
            "api/v1/auth/login",
            json_body={
                "email": self.args.tenant_email,
                "password": tenant_password,
                "tenantId": self.args.tenant_id,
            },
        )
        self.platform_headers = {"Authorization": f"Bearer {admin['accessToken']}"}
        self.tenant_headers = {
            "Authorization": f"Bearer {tenant['accessToken']}",
            "x-tenant-id": self.args.tenant_id,
        }
        self.platform_refresh_token = str(admin["refreshToken"])
        self.tenant_refresh_token = str(tenant["refreshToken"])
        self.platform_access_expires_at = time.monotonic() + float(admin["expiresInSeconds"])
        self.tenant_access_expires_at = time.monotonic() + float(tenant["expiresInSeconds"])

    def _create_kb(self, name: str) -> str:
        body = self._json(
            "POST",
            "api/v1/knowledge-bases",
            self.platform_headers,
            json_body={"name": name, "description": "Disposable real OCR E2E fixture"},
            expected=201,
        )
        kb_id = str(body["id"])
        self.resources.knowledge_bases.append(kb_id)
        return kb_id

    def _upload_scanned_pdf(self, kb_id: str, spec: VersionSpec) -> tuple[str, bytes]:
        content = _image_only_pdf(spec)
        assert spec.marker.encode() not in content, "fixture accidentally contains searchable text"
        digest = hashlib.sha256(content).hexdigest()
        upload = self._json(
            "POST",
            f"api/v1/knowledge-bases/{kb_id}/docs/upload-url",
            self.platform_headers,
            json_body={
                "fileName": SAME_FILE_NAME,
                "mimeType": "application/pdf",
                "fileSizeBytes": len(content),
                "contentHash": digest,
            },
        )
        upload_url, upload_headers = self._object_store_request(
            str(upload["uploadUrl"]), dict(upload.get("headers") or {})
        )
        put = self.client.put(upload_url, content=content, headers=upload_headers)
        _require_status(put, {200, 201, 204})
        completed = self._json(
            "POST",
            f"api/v1/knowledge-bases/{kb_id}/docs/complete-upload",
            self.platform_headers,
            json_body={
                "uploadSessionId": upload["uploadSessionId"],
                "etag": put.headers.get("etag"),
                "fileSizeBytes": len(content),
            },
            expected=201,
        )
        assert completed["fileName"] == SAME_FILE_NAME
        assert completed["contentHash"] == digest
        document_id = str(completed["id"])
        self.resources.documents.append((kb_id, document_id))
        return document_id, content

    def _wait_document(self, kb_id: str, document_id: str) -> dict[str, Any]:
        deadline = time.monotonic() + self.args.index_timeout
        while time.monotonic() < deadline:
            document = self._json(
                "GET",
                f"api/v1/knowledge-bases/{kb_id}/docs/{document_id}",
                self.platform_headers,
            )
            if document["indexStatus"] == "ready":
                return document
            if document["indexStatus"] == "failed":
                raise AssertionError(json.dumps(document, ensure_ascii=False))
            time.sleep(self.args.poll_interval)
        raise AssertionError(f"document {document_id} did not become ready")

    @staticmethod
    def _object_store_request(
        signed_url: str, headers: dict[str, str] | None = None
    ) -> tuple[str, dict[str, str]]:
        """Connect through an internal MinIO origin while preserving the signed public Host."""
        headers = dict(headers or {})
        connect_base = (
            os.getenv("KB_E2E_OBJECT_STORE_CONNECT_BASE_URL", "").strip()
            or os.getenv("KB_E2E_UPLOAD_CONNECT_BASE_URL", "").strip()
        )
        if not connect_base:
            return signed_url, headers
        signed = urlsplit(signed_url)
        connect = urlsplit(connect_base)
        if connect.scheme not in {"http", "https"} or not connect.netloc:
            raise RuntimeError("KB_E2E object-store connect base must be an HTTP(S) origin")
        headers["Host"] = signed.netloc
        return (
            urlunsplit((connect.scheme, connect.netloc, signed.path, signed.query, signed.fragment)),
            headers,
        )

    def _create_and_publish_expert(self, kb_id: str, suffix: str, run_tag: str) -> str:
        expert = self._json(
            "POST",
            "api/v1/experts",
            self.platform_headers,
            json_body={
                "name": f"KB E2E {suffix} {run_tag}",
                "categoryId": self.args.category_id,
                "abilityIntro": "Disposable knowledge citation acceptance Expert",
                "instructions": (
                    "Answer only from the supplied knowledge context. Include its [cite_N] marker "
                    "verbatim and never use knowledge from another Expert."
                ),
                "knowledgeBaseIds": [kb_id],
            },
            expected=201,
        )
        expert_id = str(expert["id"])
        self.resources.experts.append(expert_id)
        published = self._json(
            "PATCH",
            f"api/v1/experts/{expert_id}/status",
            self.platform_headers,
            json_body={"status": "published"},
        )
        assert published["status"] == "published"
        return expert_id

    def _grant_plan_access(self, expert_ids: list[str]) -> None:
        current = self._json("GET", "api/v1/plan-market/current-subscription", self.tenant_headers)
        plan = current["plan"]
        self.plan_id = str(plan["id"])
        self.original_plan_expert_ids = [str(item) for item in plan.get("expertIds") or []]
        temporary = list(dict.fromkeys([*self.original_plan_expert_ids, *expert_ids]))
        # Mark first: if the server commits but the response is lost, finally still restores the
        # exact original list instead of leaving the shared Plan mutated.
        self.plan_modified = True
        self._json(
            "PUT",
            f"api/v1/plans/{self.plan_id}/experts",
            self.platform_headers,
            json_body={"expertIds": temporary},
        )

    def _restore_plan_access(self) -> None:
        if not self.plan_modified or self.plan_id is None:
            return
        self._json(
            "PUT",
            f"api/v1/plans/{self.plan_id}/experts",
            self.platform_headers,
            json_body={"expertIds": self.original_plan_expert_ids},
        )
        self.plan_modified = False

    def _unlist_expert(self, expert_id: str) -> None:
        if expert_id in self.unlisted_expert_ids:
            return
        unlisted = self._json(
            "PATCH",
            f"api/v1/experts/{expert_id}/status",
            self.platform_headers,
            json_body={"status": "unlisted"},
        )
        assert unlisted["status"] == "unlisted"
        self.unlisted_expert_ids.add(expert_id)

    def _chat_and_assert(
        self,
        expert_id: str,
        kb_id: str,
        document_id: str,
        spec: VersionSpec,
        *,
        forbidden: list[str],
    ) -> TurnResult:
        session = self._json(
            "POST",
            "api/v1/chat/sessions",
            self.tenant_headers,
            json_body={"expertId": expert_id},
            expected=201,
        )
        session_id = str(session["id"])
        self.resources.sessions.append(session_id)
        result = self._turn(session_id, spec.question)
        assert not result.errors, json.dumps(result.errors, ensure_ascii=False)
        assert result.sources, "chat emitted no retrieval sources"
        assert result.turn_id
        assert "[cite_" in result.answer, f"answer omitted citation marker: {result.answer!r}"
        serialized = json.dumps(result.sources, ensure_ascii=False)
        assert spec.marker in serialized, f"OCR marker missing from citations: {serialized}"
        for marker in forbidden:
            assert marker not in serialized and marker not in result.answer
        for source in result.sources:
            assert source["knowledgeBaseId"] == kb_id
            assert source["documentId"] == document_id
            assert source["fileName"] == SAME_FILE_NAME
            assert source["hitText"]
            assert source["locator"]
            assert source["previewUrl"].startswith(f"/api/v1/chat/turns/{result.turn_id}/")
            assert source["downloadUrl"].startswith(f"/api/v1/chat/turns/{result.turn_id}/")
            for internal_key in (
                "sourceSha",
                "sourceSha256",
                "indexDocumentId",
                "referenceId",
            ):
                assert internal_key not in source
        return result

    def _turn(self, session_id: str, question: str) -> TurnResult:
        result = TurnResult()
        with self.client.stream(
            "POST",
            self._absolute(f"api/v1/chat/sessions/{session_id}/turns"),
            headers=self.tenant_headers,
            json={"question": question},
        ) as response:
            _require_status(response, {200})
            for event_name, payload in _iter_sse(response.iter_lines()):
                result.raw_events.append((event_name, payload))
                if event_name == "turn_started":
                    result.turn_id = str(payload.get("turnId") or "")
                elif event_name == "sources":
                    result.sources.extend(payload.get("documents") or [])
                elif event_name == "message_delta":
                    result.answer += str(payload.get("delta") or payload.get("text") or "")
                elif event_name == "error":
                    result.errors.append(payload)
        return result

    def _assert_citation_io(self, turn: TurnResult, original: bytes, spec: VersionSpec) -> None:
        citation = turn.sources[0]
        preview = self._json("GET", citation["previewUrl"], self.tenant_headers)
        assert preview["citationId"] == citation["citationId"]
        assert spec.marker in preview["hitText"]
        assert preview["content"] == preview["hitText"]
        download = self._json("GET", citation["downloadUrl"], self.tenant_headers)
        download_url, download_headers = self._object_store_request(
            self._absolute(download["downloadUrl"])
        )
        fetched = self.client.get(download_url, headers=download_headers)
        _require_status(fetched, {200})
        assert hashlib.sha256(fetched.content).digest() == hashlib.sha256(original).digest()

    def _assert_replay_sources(self, turn: TurnResult) -> None:
        response = self.client.get(
            self._absolute(f"api/v1/chat/turns/{turn.turn_id}/events"),
            headers=self.tenant_headers,
        )
        _require_status(response, {200})
        replayed = [
            payload for name, payload in _iter_sse(response.text.splitlines()) if name == "sources"
        ]
        assert replayed
        assert replayed[0]["documents"] == turn.sources

    def _assert_citation_survives_delete(
        self, turn: TurnResult, original: bytes, spec: VersionSpec
    ) -> None:
        # The Turn pins an immutable source generation, so both the OCR hit and exact source bytes
        # remain available after the mutable source Document is soft-deleted.
        self._assert_citation_io(turn, original, spec)

    def _delete_document(self, kb_id: str, document_id: str) -> None:
        response = self.client.delete(
            self._absolute(f"api/v1/knowledge-bases/{kb_id}/docs/{document_id}"),
            headers=self.platform_headers,
        )
        _require_status(response, {204})

    def _delete_kb(self, kb_id: str) -> None:
        response = self.client.delete(
            self._absolute(f"api/v1/knowledge-bases/{kb_id}"), headers=self.platform_headers
        )
        _require_status(response, {204})

    def _assert_kb_deleted(self, kb_id: str) -> None:
        response = self._request("GET", f"api/v1/knowledge-bases/{kb_id}", self.platform_headers)
        assert response.status_code == 404

    def _refresh_for(self, headers: dict[str, str]) -> None:
        platform = headers is self.platform_headers
        refresh_token = self.platform_refresh_token if platform else self.tenant_refresh_token
        payload: dict[str, Any] = {"refreshToken": refresh_token}
        if not platform:
            payload["tenantId"] = self.args.tenant_id
        response = self.client.post(self._absolute("api/v1/auth/refresh"), json=payload)
        _require_status(response, {200})
        body = response.json()
        headers["Authorization"] = f"Bearer {body['accessToken']}"
        expires_at = time.monotonic() + float(body["expiresInSeconds"])
        if platform:
            self.platform_refresh_token = str(body["refreshToken"])
            self.platform_access_expires_at = expires_at
        else:
            self.tenant_refresh_token = str(body["refreshToken"])
            self.tenant_access_expires_at = expires_at

    def _request(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None,
        *,
        json_body: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> httpx.Response:
        auth_headers = headers is self.platform_headers or headers is self.tenant_headers
        if auth_headers and headers:
            expires_at = (
                self.platform_access_expires_at
                if headers is self.platform_headers
                else self.tenant_access_expires_at
            )
            if time.monotonic() >= expires_at - 60:
                self._refresh_for(headers)
        request_options: dict[str, Any] = {"headers": headers, "json": json_body}
        if timeout is not None:
            request_options["timeout"] = timeout
        response = self.client.request(method, self._absolute(path), **request_options)
        if response.status_code == 401 and auth_headers:
            assert headers is not None
            self._refresh_for(headers)
            response = self.client.request(method, self._absolute(path), **request_options)
        return response

    def _json(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        *,
        json_body: dict[str, Any] | None = None,
        expected: int = 200,
    ) -> dict[str, Any]:
        response = self._request(method, path, headers, json_body=json_body)
        _require_status(response, {expected})
        return response.json()

    def _absolute(self, path_or_url: str) -> str:
        return urljoin(self.base_url, path_or_url)

    def _best_effort(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        *,
        json_body: dict[str, Any] | None = None,
    ) -> None:
        try:
            self._request(method, path, headers, json_body=json_body, timeout=30)
        except httpx.HTTPError:
            pass


def _image_only_pdf(spec: VersionSpec) -> bytes:
    image = Image.new("RGB", (1654, 2339), "white")
    draw = ImageDraw.Draw(image)
    font = _font(66)
    small = _font(44)
    draw.text((120, 180), "SCANNED POLICY ACCEPTANCE", fill="black", font=font)
    draw.text((120, 420), spec.label, fill="black", font=small)
    draw.text((120, 650), spec.fact, fill="black", font=font)
    draw.text((120, 890), f"Verification marker {spec.marker}", fill="black", font=font)
    draw.rectangle((90, 130, 1560, 1080), outline="black", width=5)
    output = io.BytesIO()
    image.save(output, format="PDF", resolution=150.0)
    return output.getvalue()


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf",
    ):
        if Path(path).exists():
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


def _iter_sse(lines) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = "message"
    data_lines: list[str] = []
    for raw in lines:
        line = raw.decode() if isinstance(raw, bytes) else str(raw)
        if line == "":
            if data_lines:
                payload = json.loads("\n".join(data_lines))
                events.append(
                    (event_name, payload if isinstance(payload, dict) else {"data": payload})
                )
            event_name = "message"
            data_lines = []
        elif line.startswith("event:"):
            event_name = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        payload = json.loads("\n".join(data_lines))
        events.append((event_name, payload if isinstance(payload, dict) else {"data": payload}))
    return events


def _require_status(response: httpx.Response, expected: set[int]) -> None:
    if response.status_code in expected:
        return
    try:
        body = json.dumps(response.json(), ensure_ascii=False)
    except ValueError:
        body = response.text[:2_000]
    raise AssertionError(
        f"{response.request.method} {response.request.url} -> {response.status_code}: {body}"
    )


def _required_secret(env_name: str) -> str:
    value = os.environ.get(env_name, "")
    if not value:
        raise SystemExit(f"required environment variable {env_name} is not set")
    return value


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:15000")
    parser.add_argument("--admin-email", required=True)
    parser.add_argument("--admin-password-env", default="KB_E2E_ADMIN_PASSWORD")
    parser.add_argument("--tenant-email", required=True)
    parser.add_argument("--tenant-password-env", default="KB_E2E_TENANT_PASSWORD")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--category-id", required=True)
    parser.add_argument("--index-timeout", type=float, default=900)
    parser.add_argument("--http-timeout", type=float, default=900)
    parser.add_argument("--poll-interval", type=float, default=2)
    parser.add_argument("--keep-resources", action="store_true")
    return parser.parse_args()


def main() -> int:
    acceptance = Acceptance(_parse_args())
    try:
        acceptance.run()
        return 0
    finally:
        acceptance.cleanup()
        acceptance.close()


if __name__ == "__main__":
    sys.exit(main())

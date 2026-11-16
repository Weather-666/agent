from __future__ import annotations

import httpx
import pytest

from app.clients.docling_client import DoclingClient, _annotate_source_locators
from app.core.config import Settings


def test_locator_requires_docling_page_boundaries() -> None:
    plain = "slide text without a boundary"
    assert (
        _annotate_source_locators(
            plain,
            file_name="deck.pptx",
            page_break_placeholder="<!-- page -->",
        )
        == plain
    )

    marked = _annotate_source_locators(
        "first<!-- page -->second",
        file_name="deck.pptx",
        page_break_placeholder="<!-- page -->",
    )
    assert "expert-source-locator: slide=1" in marked
    assert "expert-source-locator: slide=2" in marked


@pytest.mark.asyncio
async def test_conversion_sends_configured_ocr_options() -> None:
    captured = b""
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured
        paths.append(request.url.path)
        if request.url.path == "/v1/convert/file/async":
            captured = request.content
            return httpx.Response(200, json={"task_id": "task-1", "task_status": "pending"})
        if request.url.path == "/v1/status/poll/task-1":
            return httpx.Response(200, json={"task_id": "task-1", "task_status": "success"})
        if request.url.path == "/v1/result/task-1":
            return httpx.Response(
                200, json={"document": {"md_content": "English 中文 mixed text"}}
            )
        return httpx.Response(404)

    client = DoclingClient(
        Settings(
            docling_base_url="http://docling.test",
            docling_ocr_languages=["en", "zh"],
            _env_file=None,
        ),
        transport=httpx.MockTransport(handler),
    )

    assert await client.convert_to_markdown("mixed.pdf", b"pdf") == "English 中文 mixed text"
    assert b'name="do_ocr"' in captured and b"true" in captured
    assert b'name="force_ocr"' in captured and b"false" in captured
    assert captured.count(b'name="ocr_lang"') == 2
    assert b"expert-source-page-break" in captured
    assert paths == [
        "/v1/convert/file/async",
        "/v1/status/poll/task-1",
        "/v1/result/task-1",
    ]

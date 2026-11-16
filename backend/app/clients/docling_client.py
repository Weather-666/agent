from __future__ import annotations

import asyncio

import httpx

from app.core.config import Settings
from app.core.errors import ApiError


class DoclingClient:
    """Client for the pinned docling-serve v1 asynchronous conversion contract."""

    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = (settings.docling_base_url or "").rstrip("/")
        self.timeout = settings.docling_timeout_seconds
        self.do_ocr = settings.docling_do_ocr
        self.force_ocr = settings.docling_force_ocr
        self.ocr_languages = list(settings.docling_ocr_languages)
        self.page_break_placeholder = settings.docling_page_break_placeholder
        self.transport = transport

    async def convert_to_markdown(self, file_name: str, content: bytes) -> str:
        if not self.base_url:
            raise ApiError(503, "DOCLING_NOT_CONFIGURED", "Docling service is not configured")
        markdown = await self._convert(file_name, content)
        return _annotate_source_locators(
            markdown,
            file_name=file_name,
            page_break_placeholder=self.page_break_placeholder,
        )

    async def _convert(self, file_name: str, content: bytes) -> str:
        files = {"files": (file_name, content)}
        data: dict[str, str | list[str]] = {
            "to_formats": "md",
            "do_ocr": str(self.do_ocr).lower(),
            "force_ocr": str(self.force_ocr).lower(),
            "table_mode": "accurate",
            "do_table_structure": "true",
            "md_page_break_placeholder": self.page_break_placeholder,
        }
        if self.ocr_languages:
            data["ocr_lang"] = self.ocr_languages
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                transport=self.transport,
                trust_env=False,
            ) as client:
                submit = await client.post(
                    "/v1/convert/file/async",
                    files=files,
                    data=data,
                )
                submit.raise_for_status()
                submit_body = submit.json() or {}
                task_id = submit_body.get("task_id")
                if not task_id:
                    raise ApiError(
                        502, "DOCLING_FAILED", "Docling async submit returned no task_id"
                    )

                state = str(submit_body.get("task_status") or "")
                # The pinned 1.31 contract is pending -> started -> success | failure.
                for _ in range(200):
                    if state == "success":
                        break
                    if state in {"failure", "partial_success", "skipped"}:
                        raise ApiError(
                            502, "DOCLING_FAILED", f"Docling async conversion failed: {state}"
                        )
                    if state not in {"pending", "started"}:
                        raise ApiError(
                            502,
                            "DOCLING_FAILED",
                            "Docling async conversion returned an invalid task status",
                        )
                    status = await client.get(f"/v1/status/poll/{task_id}?wait=3")
                    status.raise_for_status()
                    state = str((status.json() or {}).get("task_status") or "")
                    if state != "success":
                        await asyncio.sleep(0.5)
                if state != "success":
                    raise ApiError(502, "DOCLING_FAILED", "Docling async conversion timed out")

                result = await client.get(f"/v1/result/{task_id}")
                result.raise_for_status()
        except (httpx.HTTPError, RuntimeError, TypeError, ValueError) as exc:
            raise ApiError(502, "DOCLING_FAILED", "Docling conversion failed") from exc
        return _extract_markdown(result)


def _extract_markdown(response: httpx.Response) -> str:
    try:
        data = response.json()
        document = data["document"]
        markdown = document["md_content"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(502, "DOCLING_BAD_RESULT", "Docling returned invalid markdown") from exc
    if not isinstance(markdown, str) or not markdown.strip():
        raise ApiError(502, "DOCLING_BAD_RESULT", "Docling returned empty markdown")
    return markdown


def _annotate_source_locators(
    markdown: str,
    *,
    file_name: str,
    page_break_placeholder: str,
) -> str:
    """Add only locators proven by Docling's page/slide boundary marker.

    A file without an emitted boundary is left untouched; the first page/slide is never guessed.
    """
    if not page_break_placeholder or page_break_placeholder not in markdown:
        return markdown
    extension = file_name.lower().rsplit(".", 1)[-1]
    field = "slide" if extension in {"ppt", "pptx"} else "page"
    annotated = [
        f"<!-- expert-source-locator: {field}={number} -->\n{page.strip()}"
        for number, page in enumerate(markdown.split(page_break_placeholder), start=1)
    ]
    return "\n\n".join(annotated).strip()

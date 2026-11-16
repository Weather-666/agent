from __future__ import annotations

import httpx
import pytest

from app.clients.lightrag_client import LightRagClient, client_for_kb
from app.core.config import Settings
from app.core.errors import ApiError


def test_client_for_kb_has_no_global_fallback() -> None:
    with pytest.raises(ApiError) as missing:
        client_for_kb(Settings(), "kb_unassigned", {})
    assert missing.value.code == "LIGHTRAG_INSTANCE_NOT_ASSIGNED"


@pytest.mark.asyncio
async def test_client_validates_health_workspace_and_api_key() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        assert request.headers["X-API-Key"] == "test-key"
        return httpx.Response(200, json={"configuration": {"workspace": "kb_pool_01"}})

    client = LightRagClient(
        "http://lightrag.test",
        "test-key",
        transport=httpx.MockTransport(handler),
    )
    health = await client.validate_workspace("kb_pool_01")
    assert health["configuration"]["workspace"] == "kb_pool_01"


@pytest.mark.asyncio
async def test_client_rejects_health_without_workspace_identity() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            200,
            json={"status": "healthy", "core_version": "1.5.6", "api_version": "0328"},
        )
    )
    client = LightRagClient("http://lightrag.test", None, transport=transport)

    with pytest.raises(ApiError) as invalid:
        await client.validate_workspace("kb_pool_01")
    assert invalid.value.code == "LIGHTRAG_WORKSPACE_UNVERIFIED"


@pytest.mark.asyncio
async def test_client_rejects_workspace_mismatch() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(200, json={"configuration": {"workspace": "other"}})
    )
    client = LightRagClient("http://lightrag.test", None, transport=transport)

    with pytest.raises(ApiError) as mismatch:
        await client.validate_workspace("kb_pool_01")
    assert mismatch.value.code == "LIGHTRAG_WORKSPACE_MISMATCH"
    assert mismatch.value.details == {
        "expectedWorkspace": "kb_pool_01",
        "actualWorkspace": "other",
    }


@pytest.mark.asyncio
async def test_client_clear_documents_requires_explicit_success() -> None:
    async def success(request: httpx.Request) -> httpx.Response:
        assert request.method == "DELETE"
        assert request.url.path == "/documents"
        return httpx.Response(200, json={"status": "success"})

    client = LightRagClient(
        "http://lightrag.test",
        None,
        transport=httpx.MockTransport(success),
    )
    await client.clear_documents()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected_code"),
    [
        ("busy", "LIGHTRAG_CLEAR_BUSY"),
        ("partial_success", "LIGHTRAG_CLEAR_PARTIAL"),
        ("fail", "LIGHTRAG_CLEAR_FAILED"),
        ("unknown", "LIGHTRAG_CLEAR_INVALID_RESPONSE"),
    ],
)
async def test_client_clear_documents_rejects_non_success(
    status: str, expected_code: str
) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json={"status": status}))
    client = LightRagClient("http://lightrag.test", None, transport=transport)

    with pytest.raises(ApiError) as rejected:
        await client.clear_documents()
    assert rejected.value.code == expected_code

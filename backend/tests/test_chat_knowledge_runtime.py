from __future__ import annotations

import httpx
import pytest

from app.clients.acp_gateway import _upstream_error
from app.clients.lightrag_client import LightRagClient
from app.core.errors import ApiError


@pytest.mark.asyncio
async def test_lightrag_query_data_groups_the_current_chunk_shape() -> None:
    def response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": {
                    "chunks": [
                        {
                            "chunk_id": "chunk-1",
                            "reference_id": "index-doc-1",
                            "file_path": "kb-kb_a--doc-doc_a--aaaaaaaaaaaaaaaa.md",
                            "content": "<!-- expert-source-locator: page=12 -->\nFirst hit",
                        },
                        {
                            "chunk_id": "chunk-2",
                            "reference_id": "index-doc-1",
                            "file_path": "kb-kb_a--doc-doc_a--aaaaaaaaaaaaaaaa.md",
                            "content": "Second hit",
                        },
                    ]
                },
                "metadata": {"mode": "hybrid"},
            },
        )

    client = LightRagClient(
        "http://lightrag.test",
        None,
        transport=httpx.MockTransport(response),
    )

    result = await client.query_data("question")

    assert result == {
        "references": [
            {
                "reference_id": "index-doc-1",
                "file_path": "kb-kb_a--doc-doc_a--aaaaaaaaaaaaaaaa.md",
                "content": [
                    {
                        "content": "<!-- expert-source-locator: page=12 -->\nFirst hit",
                        "chunk_id": "chunk-1",
                    },
                    {"content": "Second hit", "chunk_id": "chunk-2"},
                ],
            }
        ],
        "metadata": {"mode": "hybrid"},
    }


@pytest.mark.asyncio
async def test_lightrag_query_data_treats_no_results_as_empty_evidence() -> None:
    def response(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "status": "failure",
                "message": "Query returned no results",
                "data": {},
                "metadata": {"failure_reason": "no_results", "mode": "hybrid"},
            },
        )

    client = LightRagClient(
        "http://lightrag.test",
        None,
        transport=httpx.MockTransport(response),
    )

    assert await client.query_data("question") == {
        "references": [],
        "metadata": {"failure_reason": "no_results", "mode": "hybrid"},
    }


@pytest.mark.asyncio
async def test_lightrag_query_timeout_has_a_typed_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow query", request=request)

    client = LightRagClient(
        "http://lightrag.test",
        None,
        timeout=0.01,
        transport=httpx.MockTransport(timeout),
    )

    with pytest.raises(ApiError) as raised:
        await client.query_data("question")

    assert raised.value.code == "KNOWLEDGE_RETRIEVAL_TIMEOUT"
    assert raised.value.status_code == 504


def test_gateway_capacity_error_is_normalized() -> None:
    request = httpx.Request("POST", "http://gateway.test/acp/expert/turn")
    response = httpx.Response(
        429,
        request=request,
        json={"code": "POOL_FULL", "message": "internal capacity details"},
    )

    error = _upstream_error(response, stream=True)

    assert error.code == "ACP_CAPACITY_EXHAUSTED"
    assert error.details == {
        "statusCode": 429,
        "retryable": True,
        "upstreamCode": "POOL_FULL",
        "queueSupported": False,
    }

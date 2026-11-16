from __future__ import annotations

import json

import httpx
import pytest

from app.clients.lightrag_provider import ControllerLightRagProvider


@pytest.mark.asyncio
async def test_controller_provider_contract_is_authenticated_and_idempotent() -> None:
    calls: list[tuple[str, str, str | None]] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        calls.append(
            (
                request.method,
                request.url.path,
                request.headers.get("authorization"),
            )
        )
        if request.url.path == "/v1/instances/reconcile":
            assert json.loads(request.content) == {"knowledgeBaseIds": ["kb_a"]}
            return httpx.Response(
                200,
                json={
                    "managedKnowledgeBaseIds": ["kb_a"],
                    "missingKnowledgeBaseIds": [],
                    "orphanKnowledgeBaseIds": [],
                },
            )
        if request.method == "DELETE":
            return httpx.Response(404, json={"detail": "already absent"})
        return httpx.Response(
            200,
            json={
                "provider": "docker",
                "providerRef": "experts-lightrag-a",
                "baseUrl": "http://experts-lightrag-a:9621",
                "workspace": "kb_workspace_a",
                "status": "ready",
            },
        )

    provider = ControllerLightRagProvider(
        "http://controller",
        "secret",
        timeout=2,
        transport=httpx.MockTransport(handle),
    )
    first = await provider.ensure("kb_a")
    second = await provider.health("kb_a")
    await provider.delete("kb_a")
    reconciled = await provider.reconcile(["kb_a"])

    assert first == second
    assert first.workspace == "kb_workspace_a"
    assert reconciled["missingKnowledgeBaseIds"] == []
    assert [item[:2] for item in calls] == [
        ("PUT", "/v1/instances/kb_a"),
        ("GET", "/v1/instances/kb_a"),
        ("DELETE", "/v1/instances/kb_a"),
        ("POST", "/v1/instances/reconcile"),
    ]
    assert all(item[2] == "Bearer secret" for item in calls)

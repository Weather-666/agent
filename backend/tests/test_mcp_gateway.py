from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from app.clients.gateway_admin import (
    GatewayAdminClient,
    GatewayMcpRouteUpsert,
    GatewayRouteAuth,
    GatewayRouteMatch,
    GatewayVirtualKeyUpsert,
)
from app.clients.mcp_gateway import McpGatewayClient
from app.core.config import Settings
from app.core.errors import ApiError


@pytest.mark.asyncio
async def test_mcp_gateway_keeps_session_and_supports_real_protocol_methods() -> None:
    requests: list[dict[str, Any]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(
            {
                "payload": payload,
                "authorization": request.headers.get("Authorization"),
                "session": request.headers.get("MCP-Session-Id"),
            }
        )
        method = payload["method"]
        if method == "notifications/initialized":
            return httpx.Response(202)
        if method == "initialize":
            return httpx.Response(
                200,
                headers={"MCP-Session-Id": "session-1"},
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "protocolVersion": "2025-06-18",
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "gateway"},
                    },
                },
            )
        if method == "tools/list":
            return httpx.Response(
                200,
                json={
                    "jsonrpc": "2.0",
                    "id": payload["id"],
                    "result": {
                        "tools": [
                            {
                                "name": "marker",
                                "description": "Known marker",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    },
                },
            )
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": payload["id"],
                "result": {
                    "content": [{"type": "text", "text": "MARKER_OK"}],
                    "isError": False,
                },
            },
        )

    client = McpGatewayClient(
        Settings(acp_gateway_base_url="http://127.0.0.1:8080"),
        transport=httpx.MockTransport(handler),
    )
    key = SecretStr("secret-key")

    initialized = await client.initialize("/mcp/connectors/abc", key)
    tools = await client.list_tools("/mcp/connectors/abc", key)
    result = await client.call_tool("/mcp/connectors/abc", key, "marker")

    assert initialized.protocolVersion == "2025-06-18"
    assert [tool.name for tool in tools] == ["marker"]
    assert result.isError is False
    assert [item["payload"]["method"] for item in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert requests[0]["session"] is None
    assert all(item["session"] == "session-1" for item in requests[1:])
    assert all(item["authorization"] == "Bearer secret-key" for item in requests)


@pytest.mark.asyncio
async def test_gateway_admin_mcp_route_and_key_upserts_are_idempotent() -> None:
    client = GatewayAdminClient(Settings(acp_gateway_admin_url="http://127.0.0.1:8019"))
    routes: dict[str, dict[str, Any]] = {}
    keys: dict[str, dict[str, Any]] = {}
    writes: list[tuple[str, str]] = []

    async def request(
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        if path.startswith("/admin/mcp/routes/"):
            route_id = path.rsplit("/", 1)[-1]
            if method == "GET":
                return routes.get(route_id)
            writes.append((method, path))
            routes[route_id] = dict(kwargs["json"])
            return routes[route_id]
        if path == "/admin/mcp/routes":
            writes.append((method, path))
            payload = dict(kwargs["json"])
            routes[payload["id"]] = payload
            return payload
        if path.startswith("/admin/virtual_keys/"):
            tail = path.removeprefix("/admin/virtual_keys/")
            if tail.endswith("/enable"):
                key_id = tail.removesuffix("/enable")
                writes.append((method, path))
                keys[key_id]["disabled"] = False
                return keys[key_id]
            key_id = tail
            if method == "GET":
                return keys.get(key_id)
            writes.append((method, path))
            previous_key = keys.get(key_id, {}).get("key", "generated-key")
            keys[key_id] = {**kwargs["json"], "key": previous_key}
            return keys[key_id]
        if path == "/admin/virtual_keys":
            writes.append((method, path))
            payload = dict(kwargs["json"])
            keys[payload["id"]] = {**payload, "key": "generated-key"}
            return keys[payload["id"]]
        raise AssertionError((method, path, allow_not_found))

    client._request = request  # type: ignore[method-assign]
    route = GatewayMcpRouteUpsert(
        id="mcp-connector-abc",
        match_policy=GatewayRouteMatch(
            path_prefix="/mcp/connectors/abc",
            methods=["POST"],
        ),
        auth_policy=GatewayRouteAuth(require_virtual_key=True),
        service_id="service/with spaces",
    )
    key = GatewayVirtualKeyUpsert(
        id="mcp-key-0123456789abcdef",
        tag="amazon-experts-mcp",
        allowed_route_ids=[route.id],
    )

    await client.upsert_mcp_route(route)
    first_key = await client.upsert_virtual_key(key)
    await client.upsert_mcp_route(route)
    second_key = await client.upsert_virtual_key(key)

    assert first_key.key is not None
    assert second_key.key is not None
    assert first_key.key.get_secret_value() == second_key.key.get_secret_value()
    assert writes == [
        ("POST", "/admin/mcp/routes"),
        ("POST", "/admin/virtual_keys"),
    ]


@pytest.mark.asyncio
async def test_gateway_admin_rejects_empty_mcp_key_allowlist_before_request() -> None:
    client = GatewayAdminClient(Settings(acp_gateway_admin_url="http://127.0.0.1:8019"))

    with pytest.raises(ApiError) as exc_info:
        await client.upsert_virtual_key(
            GatewayVirtualKeyUpsert(id="mcp-key-0123456789abcdef")
        )

    assert exc_info.value.code == "EXPERT_MCP_ROUTE_ALLOWLIST_EMPTY"

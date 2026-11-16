from __future__ import annotations

import hashlib
import itertools
import json
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.core.config import Settings
from app.core.errors import ApiError


_PROTOCOL_VERSION = "2025-06-18"


class McpInitializeResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    protocolVersion: str
    capabilities: dict[str, Any] = Field(default_factory=dict)
    serverInfo: dict[str, Any] = Field(default_factory=dict)


class McpTool(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str
    description: str = ""
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class McpToolListPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    tools: list[McpTool]
    nextCursor: str = ""


class McpToolCallResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: Any = None
    structuredContent: Any = None
    isError: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict, alias="_meta")


class McpGatewayClient:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.base_url = settings.acp_gateway_base_url
        self.timeout = settings.mcp_gateway_timeout_seconds
        self._request_ids = itertools.count(1)
        self._sessions: dict[tuple[str, str], str] = {}
        self._transport = transport

    async def initialize(
        self,
        route_path: str,
        virtual_key: SecretStr,
    ) -> McpInitializeResult:
        value = await self._request(
            route_path,
            virtual_key,
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {
                    "name": "amazon-experts-backend",
                    "version": "1.0.0",
                },
            },
        )
        result = _validate_result(
            McpInitializeResult,
            value,
            "MCP initialize result is invalid",
        )
        await self._notify(
            route_path,
            virtual_key,
            "notifications/initialized",
            {},
        )
        return result

    async def list_tools(
        self,
        route_path: str,
        virtual_key: SecretStr,
    ) -> list[McpTool]:
        tools: list[McpTool] = []
        cursor = ""
        seen_cursors: set[str] = set()
        while True:
            params = {"cursor": cursor} if cursor else {}
            value = await self._request(
                route_path,
                virtual_key,
                "tools/list",
                params,
            )
            page = _validate_result(
                McpToolListPage,
                value,
                "MCP tool list result is invalid",
            )
            tools.extend(page.tools)
            cursor = page.nextCursor
            if not cursor:
                return tools
            if cursor in seen_cursors:
                raise _mcp_error("MCP tool list returned a repeated cursor")
            seen_cursors.add(cursor)

    async def call_tool(
        self,
        route_path: str,
        virtual_key: SecretStr,
        name: str,
        arguments: dict[str, Any] | None = None,
    ) -> McpToolCallResult:
        value = await self._request(
            route_path,
            virtual_key,
            "tools/call",
            {"name": name, "arguments": arguments or {}},
        )
        return _validate_result(
            McpToolCallResult,
            value,
            "MCP tool call result is invalid",
        )

    async def _notify(
        self,
        route_path: str,
        virtual_key: SecretStr,
        method: str,
        params: dict[str, Any],
    ) -> None:
        await self._post(
            route_path,
            virtual_key,
            {"jsonrpc": "2.0", "method": method, "params": params},
            expect_result=False,
        )

    async def _request(
        self,
        route_path: str,
        virtual_key: SecretStr,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        request_id = next(self._request_ids)
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        message = await self._post(
            route_path,
            virtual_key,
            payload,
            expect_result=True,
        )
        if message.get("id") != request_id:
            raise _mcp_error("MCP response id does not match the request")
        error = message.get("error")
        if error is not None:
            details: dict[str, object] = {}
            if isinstance(error, dict) and isinstance(error.get("code"), int):
                details["rpcCode"] = error["code"]
            raise ApiError(
                502,
                "MCP_GATEWAY_PROTOCOL_ERROR",
                "MCP Gateway returned a JSON-RPC error",
                details,
            )
        result = message.get("result")
        if not isinstance(result, dict):
            raise _mcp_error("MCP response has no result object")
        return result

    async def _post(
        self,
        route_path: str,
        virtual_key: SecretStr,
        payload: dict[str, Any],
        *,
        expect_result: bool,
    ) -> dict[str, Any]:
        if not self.base_url:
            raise ApiError(
                503,
                "MCP_GATEWAY_UNCONFIGURED",
                "MCP Gateway data plane is not configured",
            )
        if not route_path.startswith("/") or "?" in route_path or "#" in route_path:
            raise _mcp_error("MCP Route path is invalid")
        token = virtual_key.get_secret_value()
        if not token:
            raise _mcp_error("MCP VirtualKey is unavailable")
        session_key = (
            route_path,
            hashlib.sha256(token.encode("utf-8")).hexdigest(),
        )
        headers = {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "MCP-Protocol-Version": _PROTOCOL_VERSION,
            "Authorization": f"Bearer {token}",
        }
        if session_id := self._sessions.get(session_key):
            headers["MCP-Session-Id"] = session_id
        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                trust_env=False,
                transport=self._transport,
            ) as client:
                response = await client.post(route_path, headers=headers, json=payload)
        except httpx.HTTPError:
            raise _mcp_error("MCP Gateway request failed") from None
        if response.status_code >= 400:
            raise ApiError(
                502,
                "MCP_GATEWAY_REQUEST_FAILED",
                "MCP Gateway request failed",
                {"statusCode": response.status_code},
            )
        if session_id := response.headers.get("MCP-Session-Id"):
            self._sessions[session_key] = session_id
        if not expect_result:
            return {}
        return _decode_jsonrpc_response(response)


def _decode_jsonrpc_response(response: httpx.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "").casefold()
    try:
        if "text/event-stream" in content_type:
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    value = json.loads(line.removeprefix("data:").strip())
                    if isinstance(value, dict):
                        return value
            raise ValueError("missing SSE data")
        value = response.json()
    except (ValueError, json.JSONDecodeError):
        raise _mcp_error("MCP Gateway returned invalid JSON") from None
    if not isinstance(value, dict):
        raise _mcp_error("MCP Gateway returned non-object JSON")
    return value


def _validate_result(
    model: type[BaseModel],
    value: object,
    message: str,
) -> Any:
    try:
        return model.model_validate(value)
    except ValidationError:
        raise _mcp_error(message) from None


def _mcp_error(message: str) -> ApiError:
    return ApiError(502, "MCP_GATEWAY_ERROR", message)

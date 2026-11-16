from __future__ import annotations

import hmac
from typing import Any

from fastapi import APIRouter, Depends, Header
from fastapi.responses import JSONResponse, Response

from app.api.deps import get_database
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.services.knowledge_mcp_service import (
    KNOWLEDGE_MCP_TOOL_NAME,
    KnowledgeMcpService,
    knowledge_mcp_authorization,
)


router = APIRouter(prefix="/internal/mcp/knowledge", include_in_schema=False)
_PROTOCOL_VERSION = "2025-06-18"
_TOOL = {
    "name": KNOWLEDGE_MCP_TOOL_NAME,
    "description": (
        "Search the current Expert's bound knowledge bases. Use this only when the user's "
        "question needs facts from the Expert's reference documents; answer greetings, casual "
        "conversation, and general reasoning directly. Cite every used result as [cite_N]."
    ),
    "inputSchema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "minLength": 3,
                "description": "A focused search query derived from the user's question.",
            },
            "turnId": {
                "type": "string",
                "description": "The exact current turnId supplied in the internal turn metadata.",
            },
        },
        "required": ["query", "turnId"],
        "additionalProperties": False,
    },
}


@router.post("/{expert_id}")
async def knowledge_mcp(
    expert_id: str,
    message: dict[str, Any],
    authorization: str | None = Header(default=None, alias="Authorization"),
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> Response:
    expected = knowledge_mcp_authorization(settings, expert_id)
    if authorization is None or not hmac.compare_digest(authorization, expected):
        return Response(status_code=401)

    method = message.get("method")
    request_id = message.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "amazon-experts-knowledge", "version": "1.0.0"},
            },
        )
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": [_TOOL]})
    if method != "tools/call":
        return _error(request_id, -32601, "Method not found")

    params = message.get("params")
    if not isinstance(params, dict) or params.get("name") != KNOWLEDGE_MCP_TOOL_NAME:
        return _tool_error(request_id, "Unknown knowledge tool")
    arguments = params.get("arguments")
    if not isinstance(arguments, dict):
        return _tool_error(request_id, "Tool arguments must be an object")
    query = str(arguments.get("query") or "").strip()
    turn_id = str(arguments.get("turnId") or "").strip()
    if len(query) < 3 or not turn_id:
        return _tool_error(request_id, "query must contain at least 3 characters and turnId is required")

    try:
        context, _refs, knowledge_scoped = await KnowledgeMcpService(connection, settings).search(
            expert_id,
            turn_id,
            query,
        )
    except ApiError as exc:
        return _tool_error(request_id, exc.message, code=exc.code)

    if context:
        text = context.strip()
    elif knowledge_scoped:
        text = (
            "No relevant evidence was found in the bound knowledge bases. Do not invent a "
            "document-backed answer; state the limitation when the question requires those sources."
        )
    else:
        text = "No active knowledge base is bound to this Expert."
    return _result(
        request_id,
        {
            "content": [{"type": "text", "text": text}],
            "isError": False,
        },
    )


def _result(request_id: object, result: dict[str, Any]) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _error(request_id: object, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}
    )


def _tool_error(request_id: object, message: str, *, code: str | None = None) -> JSONResponse:
    payload: dict[str, Any] = {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    }
    if code:
        payload["structuredContent"] = {"code": code}
    return _result(request_id, payload)

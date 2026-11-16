from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Header
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.api.deps import get_database, get_object_store
from app.api.knowledge_mcp import _error, _result, _tool_error
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.services.library_mcp_service import LibraryMcpService, library_mcp_authorization
from app.services.library_service import LibraryService
from app.services.object_store import ObjectStore

router = APIRouter(prefix="/internal/mcp/library", include_in_schema=False)


class FindArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    turnCapability: str = Field(min_length=1, max_length=200)
    fileName: str = Field(min_length=1, max_length=255)


class ReadArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    turnCapability: str = Field(min_length=1, max_length=200)
    fileId: str = Field(min_length=1, max_length=100)
    offset: int = Field(default=0, ge=0)


_TOOLS = [
    {
        "name": "find_personal_file",
        "description": (
            "Find a personal Library file when the user mentions its name. An exact unique "
            "name is read immediately. Partial or ambiguous names return candidates: ask the "
            "user to choose; never guess. Only the current user's permanent files are visible. "
            "Use the current turnCapability from internal metadata, never a previous Turn's."
        ),
        "inputSchema": FindArguments.model_json_schema(),
    },
    {
        "name": "read_personal_file",
        "description": (
            "Read a confirmed personal file or the next text segment using nextOffset. "
            "Use fileId returned by find_personal_file and the current turnCapability. "
            "Explain partial coverage and parsing errors; never invent unseen content."
        ),
        "inputSchema": ReadArguments.model_json_schema(),
    },
]


@router.post("/{expert_id}")
async def library_mcp(
    expert_id: str,
    message: dict,
    authorization: str | None = Header(default=None),
    connection: DatabaseConnection = Depends(get_database),
    store: ObjectStore = Depends(get_object_store),
    settings: Settings = Depends(get_settings),
) -> Response:
    if authorization is None or not hmac.compare_digest(
        authorization, library_mcp_authorization(settings, expert_id)
    ):
        return Response(status_code=401)
    method, request_id = message.get("method"), message.get("id")
    if method == "notifications/initialized":
        return Response(status_code=202)
    if method == "initialize":
        return _result(request_id, {
            "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
            "serverInfo": {"name": "amazon-personal-library", "version": "1.0.0"},
        })
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": _TOOLS})
    if method != "tools/call":
        return _error(request_id, -32601, "Method not found")
    params = message.get("params")
    if not isinstance(params, dict):
        return _tool_error(request_id, "Invalid tool parameters", code="LIBRARY_TOOL_ARGUMENT_INVALID")
    service = LibraryMcpService(LibraryService(connection, store, settings))
    try:
        if params.get("name") == "find_personal_file":
            args = FindArguments.model_validate(params.get("arguments"))
            result = await service.find(expert_id, args.turnCapability, args.fileName)
        elif params.get("name") == "read_personal_file":
            args = ReadArguments.model_validate(params.get("arguments"))
            result = await service.read(expert_id, args.turnCapability, args.fileId, args.offset)
        else:
            return _tool_error(request_id, "Unknown personal Library tool")
    except ValidationError:
        return _tool_error(
            request_id, "Invalid tool arguments", code="LIBRARY_TOOL_ARGUMENT_INVALID"
        )
    except ApiError as exc:
        connection.rollback()
        return _tool_error(request_id, exc.message, code=exc.code)
    import json
    return _result(request_id, {
        "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}],
        "structuredContent": result, "isError": False,
    })

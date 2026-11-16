from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.api.deps import (
    get_acp_gateway_client,
    get_database,
    get_object_store,
    require_tenant_permission,
)
from app.clients.acp_gateway import AcpGatewayClient
from app.core.config import Settings, get_settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.chat import (
    ArchiveSessionRequest,
    ChatMessagesResponse,
    ChatSearchResponse,
    ChatSearchScope,
    ChatTurnRequest,
    CitationDownloadResponse,
    CitationPreviewResponse,
    CreateSessionRequest,
    PinSessionRequest,
    RenameSessionRequest,
    ResolvePermissionRequest,
)
from app.services.chat_service import ChatService
from app.services.library_service import LibraryService
from app.services.object_store import ObjectStore

router = APIRouter()


def build_chat_service(
    connection: DatabaseConnection,
    settings: Settings,
    acp: AcpGatewayClient,
    object_store: ObjectStore,
) -> ChatService:
    # The chat service resolves turn attachments through the library service (§7.3), so it is
    # constructed with one bound to the same connection and object store.
    library = LibraryService(connection, object_store, settings)
    return ChatService(
        connection,
        acp=acp,
        library=library,
        settings=settings,
    )


def get_chat_service(
    connection: DatabaseConnection = Depends(get_database),
    settings: Settings = Depends(get_settings),
    acp: AcpGatewayClient = Depends(get_acp_gateway_client),
    object_store: ObjectStore = Depends(get_object_store),
) -> ChatService:
    return build_chat_service(connection, settings, acp, object_store)


@router.get("/search", response_model=ChatSearchResponse)
async def search_chat_sessions(
    keyword: str = Query(
        ...,
        description="Keyword trimmed and matched against chat questions and/or answers.",
    ),
    scope: ChatSearchScope = Query(default="all"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> ChatSearchResponse:
    return service.search_sessions(
        principal,
        keyword=keyword,
        scope=scope,
        limit=limit,
        offset=offset,
    )


# --- Sessions -----------------------------------------------------------------


@router.post(
    "/sessions",
    status_code=201,
    responses={403: {"description": "EXPERT_NOT_INCLUDED_IN_PLAN"}},
)
async def create_session(
    body: CreateSessionRequest,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    return (await service.create_session(principal, body)).model_dump()


@router.get("/sessions")
async def list_sessions(
    status: str = Query(default="active", pattern="^(active|archived)$"),
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    return {"items": [s.model_dump() for s in service.list_sessions(principal, status)]}


@router.get("/sessions/{session_id}")
async def get_session(
    session_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    return service.get_session(principal, session_id).model_dump()


@router.delete("/sessions/{session_id}")
async def delete_session(
    session_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    await service.delete_session(principal, session_id)
    return {"id": session_id, "status": "deleted"}


@router.get("/sessions/{session_id}/messages", response_model=ChatMessagesResponse)
async def list_messages(
    session_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> ChatMessagesResponse:
    return ChatMessagesResponse(items=await service.list_messages(principal, session_id))


@router.get("/sessions/{session_id}/transcript")
async def get_transcript(
    session_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    # History replay: the agent-side transcript (ACP route-scoped sessions API) when available,
    # else the durable local turn records. Shape: {sessionId, messages: [{role, text}], source}.
    return await service.get_transcript(principal, session_id)


@router.patch("/sessions/{session_id}/title")
async def rename_session(
    session_id: str,
    body: RenameSessionRequest,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    return (await service.rename_session(principal, session_id, body.title)).model_dump()


@router.patch("/sessions/{session_id}/pin")
async def pin_session(
    session_id: str,
    body: PinSessionRequest,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    return service.pin_session(principal, session_id, body.isPinned).model_dump()


@router.patch("/sessions/{session_id}/archive")
def archive_session(
    session_id: str,
    body: ArchiveSessionRequest,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    return service.archive_session(principal, session_id, body.archived).model_dump()


# --- Turns --------------------------------------------------------------------


@router.post(
    "/sessions/{session_id}/turns",
    responses={
        402: {"description": "CREDIT_EXHAUSTED"},
        403: {"description": "EXPERT_NOT_INCLUDED_IN_PLAN"},
        409: {"description": "CHAT_TURN_ALREADY_RUNNING"},
    },
)
async def create_turn(
    session_id: str,
    request: Request,
    body: ChatTurnRequest,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    settings: Settings = Depends(get_settings),
    acp: AcpGatewayClient = Depends(get_acp_gateway_client),
    object_store: ObjectStore = Depends(get_object_store),
    connection: DatabaseConnection = Depends(get_database),
) -> StreamingResponse:
    # Reserve the durable Turn before pre-flight so a clean HTTP denial is still visible after
    # the caller reloads the Session. reserve_turn verifies Session ownership before writing.
    preflight_service = build_chat_service(connection, settings, acp, object_store)
    turn_id = preflight_service.reserve_turn(principal, session_id, body)
    try:
        # Authorization still happens before the SSE response starts, so callers receive the
        # original HTTP status/code instead of an empty 200 stream.
        preflight_service.validate_turn_preconditions(principal, session_id, body)
    except ApiError as exc:
        preflight_service.fail_reserved_turn(turn_id, exc.message)
        raise
    except Exception:
        preflight_service.fail_reserved_turn(
            turn_id,
            "Chat turn could not be started. Please retry.",
        )
        raise

    execution = request.app.state.chat_execution
    execution.start(
        turn_id,
        lambda conn: build_chat_service(conn, settings, acp, object_store),
        principal, session_id, body,
    )
    return StreamingResponse(
        execution.events(principal, turn_id, 0),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/turns/{turn_id}/cancel")
async def cancel_turn(
    turn_id: str,
    request: Request,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
) -> dict:
    return await request.app.state.chat_execution.cancel(principal, turn_id)


@router.get("/turns/{turn_id}/events")
async def turn_events(
    turn_id: str,
    request: Request,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    after: int | None = Query(default=None, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
) -> StreamingResponse:
    if after is None and last_event_id is not None:
        if not last_event_id.isdecimal():
            raise ApiError(400, "CHAT_EVENT_CURSOR_INVALID", "Last-Event-ID must be nonnegative")
        after = int(last_event_id)
    execution = request.app.state.chat_execution
    execution.validate_cursor(principal, turn_id, after)
    return StreamingResponse(
        execution.events(principal, turn_id, after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get(
    "/turns/{turn_id}/citations/{citation_id}/preview",
    response_model=CitationPreviewResponse,
)
async def preview_citation(
    turn_id: str,
    citation_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> CitationPreviewResponse:
    return service.preview_citation(principal, turn_id, citation_id)


@router.get(
    "/turns/{turn_id}/citations/{citation_id}/download",
    response_model=CitationDownloadResponse,
)
async def download_citation(
    turn_id: str,
    citation_id: str,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> CitationDownloadResponse:
    return service.download_citation(principal, turn_id, citation_id)


@router.post("/permissions/{permission_id}")
async def resolve_permission(
    permission_id: str,
    body: ResolvePermissionRequest,
    principal: Principal = Depends(require_tenant_permission("chat:ask")),
    service: ChatService = Depends(get_chat_service),
) -> dict:
    # Resolves a `permission_required` event raised mid-turn (e.g. tool approval).
    return await service.resolve_permission(principal, permission_id, body)

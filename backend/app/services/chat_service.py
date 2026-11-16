from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.clients.acp_gateway import AcpGatewayClient
from app.clients.lightrag_client import client_for_kb
from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.domain.chat import (
    CitationDownloadResponse,
    CitationPreviewResponse,
    ChatRetrievalSource,
    ChatSearchItem,
    ChatSearchResponse,
    ChatSearchScope,
    ChatSession,
    ChatSessionStatus,
    ChatTurnRequest,
    CreateSessionRequest,
    ResolvePermissionRequest,
)
from app.domain.expert_runtime import expert_runtime_name
from app.domain.experts import SYSTEM_DEFAULT_EXPERT_ID
from app.services._sql import is_unique_violation, json_load
from app.services.chat_repository import ChatRepository
from app.services.credit_service import CreditService
from app.services.document_repository import DocumentRepository
from app.services.expert_access_service import ExpertAccessService
from app.services.expert_service import ExpertService
from app.services.library_service import LibraryService
from app.services.library_mcp_service import library_turn_capability
from app.services.lightrag_instance_repository import LightragInstanceRepository
from app.services.knowledge_base_repository import KnowledgeBaseRepository


logger = logging.getLogger(__name__)


class ChatService:
    """Local DB is the system of record; ACP only drives compute.

    Sessions/turns are mirrored into chat_sessions/chat_turns so reads are tenant-scoped and
    survive the engine. The agent-gateway ACP data plane exposes only POST {prefix}/turn and
    POST {prefix}/permission. The thread id is generated locally at create time (no upstream
    call); a turn has no server id, so one is generated locally. The agent-assigned ACP session
    id arrives via the first turn's `session` event and is echoed back on later turns to resume
    the same instance. ACP events are translated to the public SSE contract
    (turn_started -> reasoning_delta -> message_delta -> turn_completed / error /
    permission_required) so callers do not change.
    """

    def __init__(
        self,
        connection: DatabaseConnection,
        *,
        acp: AcpGatewayClient | None = None,
        library: LibraryService | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.connection = connection
        self.acp = acp
        self.library = library
        self.settings = settings or Settings(_env_file=None)
        self.repo = ChatRepository(connection)
        self.credits = CreditService(connection, self.settings)
        self.expert_access = ExpertAccessService(connection)

    def _require_acp(self) -> AcpGatewayClient:
        if self.acp is None:
            raise ApiError(503, "ACP_UNCONFIGURED", "acp gateway client is not configured")
        return self.acp

    def _acp_route(self, row: dict, web_search_enabled: bool | None) -> _AcpRoute:
        acp = self._require_acp()
        search_enabled = web_search_enabled is True
        bound_runtime = row.get("expert_id") is not None

        if bound_runtime:
            runtime_type = str(row.get("runtime_type") or "")
            try:
                prefix = f"/acp/{expert_runtime_name(runtime_type, str(row['expert_id']))}"
            except ValueError as exc:
                raise ApiError(
                    409,
                    "CHAT_EXPERT_RUNTIME_INVALID",
                    "Chat Session has an invalid Expert runtime identity",
                ) from exc

        if search_enabled:
            if not bound_runtime:
                prefix = acp.search_route_prefix or acp.route_prefix
            column = "search"
            field = "acp_search_session_id"
        else:
            if not bound_runtime:
                prefix = acp.route_prefix
            column = "no_search"
            field = "acp_session_id"

        session_id = str(row[field]) if row.get(field) else None
        return _AcpRoute(
            route_prefix=prefix,
            search_mode="auto" if search_enabled else "off",
            session_id=session_id,
            session_column=column,
            uses_service_defaults=bound_runtime,
            thread_id=(f"{row['id']}:{column}" if bound_runtime else str(row["id"])),
        )

    def _prepare_acp_cwd(self, row: dict) -> str | None:
        acp = self._require_acp()
        agent_options = json_load(row.get("agent_options"))
        if row.get("expert_id") is not None or agent_options.get("workspaceScope") == "user":
            cwd = acp.prepare_user_cwd(
                str(row.get("tenant_id") or ""),
                str(row.get("user_id") or ""),
            )
            if agent_options.get("workspaceScope") != "user":
                # The old tenant workspace can contain another member's private files.
                # Preserve it, but never resume its ACP session under the new user boundary.
                self.repo.isolate_session_workspace(row, _now_iso())
                self.connection.commit()
                current = self.repo.get_session_row(row["tenant_id"], row["user_id"], row["id"])
                if current is None:
                    raise _session_not_found()
                if json_load(current.get("agent_options")).get("workspaceScope") != "user":
                    raise ApiError(
                        409, "CHAT_WORKSPACE_CHANGED", "Chat workspace changed; retry the request"
                    )
                row.update(current)
            return cwd
        return acp.prepare_default_cwd()

    def _set_acp_route_session(
        self, route: _AcpRoute, session_id: str, acp_session_id: str | None
    ) -> bool:
        if route.session_column == "search":
            return self.repo.set_acp_search_session_id(session_id, acp_session_id, _now_iso())
        return self.repo.set_acp_session_id(session_id, acp_session_id, _now_iso())

    async def retrieve_expert_knowledge(
        self,
        expert_id: str,
        question: str,
        turn_id: str,
        *,
        citation_offset: int = 0,
    ) -> tuple[str, list[dict], bool]:
        """Fetch exact, citation-mapped evidence when the Expert calls its knowledge tool.

        Knowledge scope is resolved platform-side through expert_knowledge_bases. LightRAG returns
        evidence only; Codex/ACP remains the answerer. A live bound KB that is not ready fails
        explicitly instead of falling back to another endpoint or stale Runtime Knowledge.
        """
        states = self.repo.knowledge_binding_states(expert_id)
        for state in states:
            if (
                state.get("knowledge_base_deleted_at") is None
                and str(state.get("knowledge_base_status") or "") == "active"
                and (
                    str(state.get("index_status") or "") != "ready"
                    or str(state.get("binding_status") or "") not in {"", "ready"}
                    or state.get("base_url") is None
                    or state.get("workspace") is None
                )
            ):
                raise ApiError(
                    503,
                    "KNOWLEDGE_INDEX_NOT_READY",
                    "A bound knowledge base index is not ready",
                    {
                        "knowledgeBaseId": str(state.get("knowledge_base_id") or ""),
                        "indexStatus": str(state.get("index_status") or "provisioning"),
                        "retryable": True,
                    },
                )
        kb_ids = self.repo.list_kb_ids_for_expert(expert_id)
        if not kb_ids:
            return "", [], False
        try:
            instances = LightragInstanceRepository(self.connection).map()
        except Exception:  # noqa: BLE001 - registry read must not fail the turn
            instances = {}
        context_parts: list[str] = []
        refs: list[dict] = []
        documents = DocumentRepository(self.connection)
        knowledge_bases = KnowledgeBaseRepository(self.connection)
        for kb_id in kb_ids:
            try:
                client = client_for_kb(self.settings, kb_id, instances)
                result = await client.query_data(
                    question,
                    mode=self.settings.lightrag_query_mode,
                    top_k=self.settings.lightrag_query_top_k,
                    chunk_top_k=self.settings.lightrag_query_chunk_top_k,
                    enable_rerank=self.settings.lightrag_query_enable_rerank,
                )
            except ApiError as exc:
                # A knowledge-bound Expert must not fall through when its isolated index is
                # unavailable; doing so would silently omit the requested public knowledge.
                raise ApiError(
                    exc.status_code,
                    exc.code,
                    exc.message,
                    {**exc.details, "knowledgeBaseId": kb_id},
                ) from exc
            raw_references = [
                reference
                for reference in (result.get("references") or [])
                if isinstance(reference, dict)
            ]
            candidates = documents.list_retrieval_sources(
                kb_id,
                pipeline_version=self.settings.knowledge_index_pipeline_version,
            )
            kb = knowledge_bases.get(kb_id)
            mapped: list[dict] = []
            for reference in raw_references:
                source = _match_retrieval_source(reference, candidates)
                chunks = _reference_chunks(reference.get("content"))
                if source is None or not chunks:
                    continue
                hit_text = _bounded_hit_text(chunks)
                locator = _reference_locator(reference, str(source["file_type"]))
                item = {
                    # Keep external identities only in the persisted internal provenance shape.
                    "referenceId": str(reference.get("reference_id") or ""),
                    "filePath": str(reference.get("file_path") or ""),
                    "content": chunks,
                    # Citation-v2 additions are denormalized so history survives rename/delete.
                    "knowledgeBaseId": kb_id,
                    "knowledgeBaseName": str(kb.name) if kb is not None else None,
                    "documentId": str(source["id"]),
                    "fileName": str(source["file_name"]),
                    "mimeType": (
                        str(source["mime_type"]) if source.get("mime_type") is not None else None
                    ),
                    "hitText": hit_text,
                    "locator": locator,
                }
                if locator.get("pageNumber") is not None or locator.get("slideNumber") is not None:
                    item["locatorProvenance"] = "docling-page-break"
                source_sha = source.get("source_sha256") or source.get("content_hash")
                if source_sha is not None:
                    item["sourceSha"] = str(source_sha)
                    item["sourceSha256"] = str(source_sha)
                if source.get("index_document_id") is not None:
                    item["indexDocumentId"] = str(source["index_document_id"])
                mapped.append(item)

            # Every chunk passed to ACP must map to one current, byte-identical source Document.
            if raw_references and len(mapped) != len(raw_references):
                raise ApiError(
                    502,
                    "KNOWLEDGE_CITATION_INCOMPLETE",
                    "Knowledge retrieval returned context without complete citation provenance",
                    {
                        "knowledgeBaseId": kb_id,
                        "referenceCount": len(raw_references),
                        "mappedReferenceCount": len(mapped),
                    },
                )
            for item in mapped:
                citation_id = f"cite_{citation_offset + len(refs) + 1}"
                item["citationId"] = citation_id
                item["previewUrl"] = f"/api/v1/chat/turns/{turn_id}/citations/{citation_id}/preview"
                item["downloadUrl"] = (
                    f"/api/v1/chat/turns/{turn_id}/citations/{citation_id}/download"
                )
                refs.append(item)
            if mapped:
                labels = "\n\n".join(f"[{item['citationId']}] {item['hitText']}" for item in mapped)
                context_parts.append(labels)
        if not context_parts:
            return "", [], True
        context = (
            "【知识库检索结果】\n"
            + "\n\n".join(context_parts)
            + "\n\n请仅依据以上资料回答，并使用对应的 [cite_N] 标注引用。\n\n"
        )
        return context, refs, True

    # --- Sessions -------------------------------------------------------------

    async def create_session(
        self, principal: Principal, request: CreateSessionRequest
    ) -> ChatSession:
        now = _now_iso()
        tenant_id = str(principal.active_tenant_id)
        user_workspace = request.expertId is not None or tenant_id == self.settings.default_tenant_id
        if request.runtimeType is not None and request.expertId is None:
            raise ApiError(
                400,
                "CHAT_EXPERT_REQUIRED",
                "runtimeType can only be selected together with expertId",
            )
        if request.expertId == SYSTEM_DEFAULT_EXPERT_ID:
            raise ApiError(
                409,
                "EXPERT_NOT_SELECTABLE",
                "The system default Expert is not available for Chat",
            )
        # The ACP data plane has no thread-create endpoint: the agent materializes a session
        # lazily on the first turn. Generate the caller-owned thread id locally.
        thread_id = f"thread_{uuid4().hex}"
        runtime_identity: dict[str, str] | None = None
        if request.expertId is not None:
            expert = ExpertService(self.connection).get(request.expertId)
            if expert.status != "published":
                raise ApiError(
                    409,
                    "EXPERT_NOT_PUBLISHED",
                    "Expert must be published before a Chat Session can be created",
                )
            enabled = [
                runtime
                for runtime in ("codex", "opencode")
                if (target := expert.runtimeConfig.get(runtime)) is not None and target.enabled
            ]
            runtime_type = request.runtimeType or (enabled[0] if enabled else None)
            if runtime_type is None or runtime_type not in enabled:
                raise ApiError(
                    409,
                    "EXPERT_RUNTIME_DISABLED",
                    "Selected runtime is not enabled for this Expert",
                )
            runtime_identity = {
                "expert_id": expert.id,
                "runtime_type": runtime_type,
            }
            self.expert_access.require_access(
                tenant_id,
                expert.id,
            )
            acp = self._require_acp()
            if user_workspace:
                acp.prepare_user_cwd(tenant_id, principal.user_id)
            else:
                acp.prepare_tenant_cwd(tenant_id)
        self.repo.create_session(
            session_id=thread_id,
            tenant_id=tenant_id,
            user_id=principal.user_id,
            title=request.title,
            agent_options={"workspaceScope": "user"} if user_workspace else {},
            runtime_identity=runtime_identity,
            now=now,
        )
        self.connection.commit()
        return ChatSession(
            id=thread_id,
            title=request.title,
            status="active",
            isPinned=False,
            expertId=(runtime_identity or {}).get("expert_id"),
            runtimeType=(runtime_identity or {}).get("runtime_type"),
            createdAt=now,
            updatedAt=now,
        )

    def list_sessions(
        self, principal: Principal, status: ChatSessionStatus = "active"
    ) -> list[ChatSession]:
        return self.repo.list_sessions(str(principal.active_tenant_id), principal.user_id, status)

    def search_sessions(
        self,
        principal: Principal,
        *,
        keyword: str,
        scope: ChatSearchScope,
        limit: int,
        offset: int,
    ) -> ChatSearchResponse:
        normalized_keyword = keyword.strip()
        if not 1 <= len(normalized_keyword) <= 200:
            raise ApiError(
                400,
                "CHAT_SEARCH_KEYWORD_INVALID",
                "keyword must contain 1 to 200 characters after trimming",
            )
        rows, total = self.repo.search_sessions(
            tenant_id=str(principal.active_tenant_id),
            user_id=principal.user_id,
            keyword=normalized_keyword,
            scope=scope,
            limit=limit,
            offset=offset,
        )
        items = [
            ChatSearchItem(
                sessionId=str(row["session_id"]),
                title=str(row["title"]) if row.get("title") is not None else None,
                matchedTurnId=str(row["matched_turn_id"]),
                matchedType=str(row["matched_type"]),
                snippet=_chat_search_snippet(str(row["matched_text"]), normalized_keyword),
            )
            for row in rows
        ]
        return ChatSearchResponse(
            items=items,
            total=total,
            limit=limit,
            offset=offset,
        )

    def get_session(self, principal: Principal, session_id: str) -> ChatSession:
        session = self.repo.get_session(
            str(principal.active_tenant_id), principal.user_id, session_id
        )
        if session is None:
            raise _session_not_found()
        return session

    async def rename_session(
        self, principal: Principal, session_id: str, title: str
    ) -> ChatSession:
        self._require_session(principal, session_id)
        self.repo.update_session_title(session_id, title, _now_iso())
        self.connection.commit()
        return self.get_session(principal, session_id)

    def pin_session(self, principal: Principal, session_id: str, is_pinned: bool) -> ChatSession:
        self._require_session(principal, session_id)
        now = _now_iso()
        self.repo.set_session_pin(session_id, is_pinned, now if is_pinned else None, now)
        self.connection.commit()
        return self.get_session(principal, session_id)

    def archive_session(self, principal: Principal, session_id: str, archived: bool) -> ChatSession:
        self._require_session(principal, session_id)
        now = _now_iso()
        self.repo.set_session_status(session_id, "archived" if archived else "active", now)
        self.connection.commit()
        return self.get_session(principal, session_id)

    async def delete_session(self, principal: Principal, session_id: str) -> None:
        self._require_session(principal, session_id)
        self.repo.delete_session(session_id, _now_iso())
        self.connection.commit()

    async def list_messages(self, principal: Principal, session_id: str) -> list[dict]:
        self._require_session(principal, session_id)
        messages: list[dict] = []
        for turn in self.repo.list_turns(session_id):
            item = turn.model_dump()
            item["retrievalRefs"] = _public_retrieval_sources(turn.retrievalRefs)
            item["reasoningText"] = _public_reasoning(turn.reasoningText)
            messages.append(item)
        return messages

    async def get_transcript(self, principal: Principal, session_id: str) -> dict:
        """Replay owner-scoped history without internal authorization metadata."""
        self._require_session(principal, session_id)
        return {
            "sessionId": session_id,
            "messages": self._local_transcript(session_id),
            "source": "local",
        }

    def _local_transcript(self, session_id: str) -> list[dict]:
        messages: list[dict] = []
        for turn in self.repo.list_turns(session_id):
            messages.append({"role": "user", "text": turn.requestText})
            if turn.reasoningText:
                messages.append({"role": "reasoning", "text": _public_reasoning(turn.reasoningText)})
            if turn.responseText:
                messages.append({"role": "assistant", "text": turn.responseText})
        return messages

    # --- Turns ----------------------------------------------------------------

    def reserve_turn(self, principal: Principal, session_id: str, request: ChatTurnRequest) -> str:
        """Persist the running Turn before the SSE response starts.

        The partial unique index on running Turns is the cross-process concurrency guard. Mapping
        its collision here keeps the public failure a stable HTTP 409 instead of a broken SSE.
        """
        row = self._require_session(principal, session_id)
        acp = self._require_acp()
        route = self._acp_route(row, request.webSearchEnabled)
        turn_id = f"turn_{uuid4().hex}"
        try:
            self.repo.create_turn(
                turn_id=turn_id,
                session_id=session_id,
                tenant_id=str(principal.active_tenant_id),
                user_id=principal.user_id,
                request_text=request.question,
                model=None if route.uses_service_defaults else acp.default_model,
                query_rewrite=False,
                multi_hop_config=None,
                token_usage_scope=route.session_column,
                runtime_identity=_runtime_identity(row),
                now=_now_iso(),
                attachments=[],
            )
            self.connection.commit()
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            self.connection.rollback()
            raise ApiError(
                409,
                "CHAT_TURN_ALREADY_RUNNING",
                "Chat Session already has a running Turn",
            ) from exc
        return turn_id

    async def stream_turn(
        self,
        principal: Principal,
        session_id: str,
        request: ChatTurnRequest,
        *,
        turn_id: str,
    ) -> AsyncIterator[str]:
        row = self._require_session(principal, session_id)
        acp = self._require_acp()
        tenant_id = principal.active_tenant_id
        cwd = self._prepare_acp_cwd(row)
        route = self._acp_route(row, request.webSearchEnabled)
        acp_session_id = route.session_id

        # Authorize referenced attachments, snapshot them for provenance, and build a bounded
        # Backend delivery capability per attachment. request_text stays the user's question; the
        # delivery URLs are appended only to the input sent to the runtime.
        attachments_snapshot, attachment_text = self._prepare_attachments(
            principal, session_id, request, turn_id=turn_id
        )
        self.repo.update_turn_attachments(turn_id, attachments_snapshot)
        self.connection.commit()

        previous_usage_snapshot = (
            self.repo.get_token_usage_baseline(
                session_id=session_id,
                tenant_id=str(tenant_id),
                user_id=principal.user_id,
                token_usage_scope=route.session_column,
                token_usage_session_id=acp_session_id,
            )
            if acp_session_id is not None
            else None
        )
        yield _sse("turn_started", {"turnId": turn_id})

        knowledge_tool_context = ""
        expert_id = row.get("expert_id")
        if expert_id is not None and self.repo.list_kb_ids_for_expert(str(expert_id)):
            knowledge_tool_context = (
                "\n\n[Internal turn metadata]\n"
                f"turnId: {turn_id}\n"
                "Pass this exact turnId when calling search_expert_knowledge. "
                "Do not repeat this metadata in the answer."
            )
        capability = library_turn_capability(self.settings, row, turn_id)
        library_tool_context = (
            "\n\n[Internal personal Library authorization]\n"
            f"turnCapability: {capability}\n"
            "When the user asks to read their personal file by name, call the namespaced MCP tool mcp__personal_library__find_personal_file. "
            "An exact unique match returns real text. Ask for clarification on candidates. "
            "Use read_personal_file for confirmed candidates or nextOffset segments. "
            "Never use a previous capability or reveal this credential. "
            "Do not claim to have read a file unless a tool returned its content."
        )
        turn_input = request.question + attachment_text + knowledge_tool_context + library_tool_context
        retrieval_refs: list[dict] = []

        result = _AcpTurnResult(
            bound_session_id=acp_session_id,
            previous_usage_snapshot=previous_usage_snapshot,
        )
        # Hold a new or resumed attempt only until it shows a sign of life. This keeps a
        # pre-output gateway failure invisible so the turn can retry once on a clean ACP
        # session without leaking a transient error to the browser.
        attempt_events: list[str] | None = []
        committed = False
        try:
            drive = self._drive_acp_turn(
                acp=acp,
                principal=principal,
                session_id=session_id,
                request=request,
                turn_input=turn_input,
                initial_acp_session_id=acp_session_id,
                cwd=cwd,
                route=route,
                turn_id=turn_id,
                result=result,
            )
            # An attempt is buffered only until it shows a sign of life. Once any
            # output, reasoning, session rebind, permission prompt, or completion arrives,
            # the resume has "taken": flush what was held and stream the rest live so
            # follow-up turns are not stalled until the whole turn completes. The one
            # clean-session retry (attempt_events is None) streams live from its first event.
            async for event in drive:
                if committed:
                    yield event
                    continue
                attempt_events.append(event)
                if (
                    result.saw_delta
                    or result.reasoning_parts
                    or result.saw_done
                    or event.startswith("event: permission_required")
                ):
                    committed = True
                    for buffered in attempt_events:
                        yield buffered
                    attempt_events = None
            # A buffered attempt that produced nothing and errored is safe to retry. Drop any
            # binding and retry once with a fresh session, streaming the retry live since no
            # model output or error was emitted to the caller yet. This covers both stale resume
            # sessions and a first-turn agent process that wedged before producing output.
            if result.error_message is not None and not committed and acp_session_id is None:
                self._set_acp_route_session(route, session_id, None)
                self.connection.commit()
                # The new ACP session starts from zero, so discard the retired session's result.
                result = _AcpTurnResult()
                attempt_events = None
                async for event in self._drive_acp_turn(
                    acp=acp,
                    principal=principal,
                    session_id=session_id,
                    request=request,
                    turn_input=turn_input,
                    initial_acp_session_id=None,
                    cwd=cwd,
                    route=route,
                    turn_id=turn_id,
                    result=result,
                    fresh_session=True,
                ):
                    yield event
            elif result.error_message is not None and not committed and acp_session_id is not None:
                result.error_message = (
                    "The saved Agent session could not be resumed. Its context was not reset; "
                    "create a new Chat Session or retry after the runtime is repaired."
                )
                attempt_events = [
                    _sse(
                        "error",
                        {
                            "code": "ACP_SESSION_RESUME_FAILED",
                            "message": result.error_message,
                            "recoverable": True,
                            "contextReset": False,
                        },
                    )
                ]
        except ApiError as exc:
            retrieval_refs = self._stored_retrieval_refs(turn_id)
            friendly_message = _friendly_acp_error_message(exc.message, exc.details)
            self._finalize(
                turn_id,
                [_normalize_answer_markdown("".join(result.parts))],
                result.stop_reason,
                friendly_message,
                reasoning_parts=result.reasoning_parts,
                token_usage_session_id=result.bound_session_id or "",
                token_usage_previous_snapshot=result.previous_usage_size,
                token_usage_snapshot=result.token_usage_snapshot,
                token_used=result.token_used,
                retrieval_refs=retrieval_refs,
            )
            yield _sse(
                "error",
                {"code": exc.code, "message": friendly_message, "details": exc.details},
            )
            return
        except asyncio.CancelledError:
            # Only the execution owner's stop/shutdown cancels this generator. Closing the
            # upstream HTTP stream propagates ACP session/cancel through the Gateway.
            retrieval_refs = self._stored_retrieval_refs(turn_id)
            self._finalize(
                turn_id,
                [_normalize_answer_markdown("".join(result.parts))],
                result.stop_reason or "cancelled",
                result.error_message,
                reasoning_parts=result.reasoning_parts,
                token_usage_session_id=result.bound_session_id or "",
                token_usage_previous_snapshot=result.previous_usage_size,
                token_usage_snapshot=result.token_usage_snapshot,
                token_used=result.token_used,
                retrieval_refs=retrieval_refs,
            )
            raise
        except Exception:
            logger.exception("Unexpected failure while streaming chat turn %s", turn_id)
            error_message = "Chat turn failed unexpectedly. Please retry."
            retrieval_refs = self._stored_retrieval_refs(turn_id)
            self._finalize(
                turn_id,
                [_normalize_answer_markdown("".join(result.parts))],
                result.stop_reason,
                error_message,
                reasoning_parts=result.reasoning_parts,
                token_usage_session_id=result.bound_session_id or "",
                token_usage_previous_snapshot=result.previous_usage_size,
                token_usage_snapshot=result.token_usage_snapshot,
                token_used=result.token_used,
                retrieval_refs=retrieval_refs,
            )
            yield _sse(
                "error",
                {"code": "CHAT_TURN_FAILED", "message": error_message},
            )
            return

        if attempt_events is not None:
            for event in attempt_events:
                yield event

        if result.error_message is None and not result.saw_done:
            result.error_message = "The reply was interrupted before completion. Please try again."
            yield _sse("error", {"message": result.error_message})

        answer = _normalize_answer_markdown("".join(result.parts))
        retrieval_refs = self._stored_retrieval_refs(turn_id)
        self._finalize(
            turn_id,
            [answer],
            result.stop_reason,
            result.error_message,
            reasoning_parts=result.reasoning_parts,
            token_usage_session_id=result.bound_session_id or "",
            token_usage_previous_snapshot=result.previous_usage_size,
            token_usage_snapshot=result.token_usage_snapshot,
            token_used=result.token_used,
            retrieval_refs=retrieval_refs,
        )
        current_row = self.repo.get_session_row(
            str(principal.active_tenant_id), principal.user_id, session_id
        )
        local_title = str((current_row or {}).get("title") or "").strip()
        if result.error_message is None and not local_title and result.bound_session_id:
            title = await self._fetch_acp_title(
                str(tenant_id), result.bound_session_id, cwd, route.route_prefix
            )
            if title:
                self.repo.update_session_title(session_id, title, _now_iso())
                self.connection.commit()
                yield _sse("session_title_updated", {"title": title})
        if result.error_message is None:
            if retrieval_refs:
                yield _sse("sources", _sources_payload(retrieval_refs))
            yield _sse("turn_completed", {"stopReason": result.stop_reason})

    async def _drive_acp_turn(
        self,
        *,
        acp: AcpGatewayClient,
        principal: Principal,
        session_id: str,
        request: ChatTurnRequest,
        turn_input: str,
        initial_acp_session_id: str | None,
        cwd: str | None,
        route: _AcpRoute,
        turn_id: str,
        result: _AcpTurnResult,
        fresh_session: bool = False,
    ) -> AsyncIterator[str]:
        reasoning_buffer = _SmoothTextBuffer(max_chars=48, punctuation=True)
        answer_buffer = _SmoothTextBuffer(max_chars=80, punctuation=True)
        current_event: str | None = None
        data_line = ""
        result.bound_session_id = initial_acp_session_id
        # Auto session title: the gateway replays the agent's title as a `session_info` event at
        # turn start. Persist it only while the local title is still empty so a user's manual
        # rename is never clobbered.
        row = self.repo.get_session_row(
            str(principal.active_tenant_id), principal.user_id, session_id
        )
        local_title = str((row or {}).get("title") or "").strip()

        capabilities = re.findall(r"lturn_turn_[0-9a-f]{32}\.[0-9a-f]{64}", turn_input)
        secret = capabilities[-1] if capabilities else ""
        reasoning_redactor = _CredentialRedactor(secret)
        answer_redactor = _CredentialRedactor(secret)

        def emit_reasoning(text: str) -> list[str]:
            if result.reasoning_parts and result.reasoning_parts[-1] == text:
                return []
            text = reasoning_redactor.push(text)
            result.reasoning_parts.append(text)
            chunk = reasoning_buffer.push(text)
            if chunk:
                return [_sse("reasoning_delta", _reasoning_delta_payload(chunk, turn_id))]
            return []

        def emit_answer(text: str) -> list[str]:
            text = answer_redactor.push(text)
            result.parts.append(text)
            result.saw_delta = True
            events: list[str] = []
            reasoning_tail = reasoning_buffer.flush()
            if reasoning_tail:
                events.append(
                    _sse("reasoning_delta", _reasoning_delta_payload(reasoning_tail, turn_id))
                )
            chunk = answer_buffer.push(text)
            if chunk:
                events.append(
                    _sse(
                        "message_delta",
                        {
                            "delta": _normalize_answer_markdown_delta(
                                chunk, at_line_start=answer_buffer.chunk_at_line_start
                            )
                        },
                    )
                )
            return events

        def flush_reasoning_tail() -> list[str]:
            pending = reasoning_redactor.finish()
            result.reasoning_parts.append(pending)
            reasoning_buffer._text += pending
            reasoning_tail = reasoning_buffer.flush()
            if reasoning_tail:
                return [_sse("reasoning_delta", _reasoning_delta_payload(reasoning_tail, turn_id))]
            return []

        def flush_answer_tail() -> list[str]:
            pending = answer_redactor.finish()
            result.parts.append(pending)
            answer_buffer._text += pending
            answer_tail = answer_buffer.flush()
            if answer_tail:
                return [
                    _sse(
                        "message_delta",
                        {
                            "delta": _normalize_answer_markdown_delta(
                                answer_tail, at_line_start=answer_buffer.chunk_at_line_start
                            )
                        },
                    )
                ]
            return []

        async for line in acp.stream_turn(
            thread_id=route.thread_id,
            input=turn_input,
            tenant_id=principal.active_tenant_id,
            session_id=initial_acp_session_id,
            cwd=cwd,
            fresh_session=fresh_session,
            search_mode=route.search_mode,
            route_prefix=route.route_prefix,
            model="" if route.uses_service_defaults else None,
        ):
            if line.startswith("event:"):
                current_event = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data_line = line[len("data:") :].strip()
            elif line == "":
                if current_event:
                    try:
                        data = json.loads(data_line) if data_line else {}
                    except json.JSONDecodeError:
                        data = {}
                    if current_event == "session":
                        sid = str(data.get("session_id") or "").strip()
                        if sid and sid != result.bound_session_id:
                            # Persist the agent-assigned id so follow-up turns resume this instance.
                            result.bind_session(sid)
                            self._set_acp_route_session(route, session_id, sid)
                            self.connection.commit()
                    elif current_event == "delta":
                        text = data.get("text")
                        if text:
                            for event in emit_answer(str(text)):
                                yield event
                    elif current_event in _ACP_REASONING_EVENTS:
                        if current_event == "tool_call":
                            _log_acp_tool_failure(
                                data, session_id=session_id, turn_id=turn_id,
                                expert_id=str((row or {}).get("expert_id") or ""),
                            )
                        if current_event == "usage":
                            token_used = _acp_token_used(data)
                            if token_used is not None:
                                result.capture_usage(
                                    token_used,
                                )
                        reasoning_text = _acp_reasoning_text(current_event, data)
                        if reasoning_text:
                            for event in emit_reasoning(reasoning_text):
                                yield event
                    elif current_event == "permission":
                        # Translate ACP permission prompts to the public permission_required shape.
                        permission_id = str(data.get("request_id") or "").strip()
                        if permission_id:
                            self.repo.save_pending_permission(
                                permission_id=permission_id,
                                session_id=session_id,
                                tenant_id=str(principal.active_tenant_id),
                                user_id=principal.user_id,
                                route_prefix=route.route_prefix,
                                now=_now_iso(),
                            )
                            self.connection.commit()
                        payload: dict = {"permissionId": permission_id or None}
                        if data.get("data") is not None:
                            payload["data"] = data["data"]
                        yield _sse("permission_required", payload)
                    elif current_event == "error":
                        result.error_message = _friendly_acp_error_message(
                            str(data.get("message") or "") or "error",
                            data.get("details") if isinstance(data.get("details"), dict) else None,
                        )
                        yield _sse("error", {"message": result.error_message})
                    elif current_event == "done":
                        result.saw_done = True
                        reason = data.get("stop_reason")
                        result.stop_reason = str(reason) if reason is not None else None
                        for event in flush_reasoning_tail():
                            yield event
                        for event in flush_answer_tail():
                            yield event
                    elif current_event == "session_info":
                        # Agents that push session_info_update (e.g. opencode) surface the title
                        # live here; the gateway wraps the raw ACP update under `data`, so it is
                        # nested. codex-acp does NOT emit it -- that title comes from the
                        # route-scoped session/list reconciliation after the turn (below).
                        title = str(((data.get("data") or {}).get("title")) or "").strip()
                        if title and not local_title:
                            self.repo.update_session_title(session_id, title, _now_iso())
                            self.connection.commit()
                            local_title = title
                            yield _sse("session_title_updated", {"title": title})
                current_event = None
                data_line = ""

        for event in flush_reasoning_tail():
            yield event
        for event in flush_answer_tail():
            yield event

    async def _fetch_acp_title(
        self, tenant_id: str, acp_session_id: str, cwd: str | None, route_prefix: str
    ) -> str | None:
        """Look up a session's auto-derived title via the route-scoped session list.

        Keyed by the agent-assigned ACP session id (chat_sessions.acp_session_id), not the local
        thread id. Pages the cwd-filtered list until the id is found; bounded so an absent id can
        never loop forever. Returns None (never raises) if the gateway is unhealthy.
        """
        acp = self._require_acp()
        cursor: str | None = None
        for _ in range(20):
            try:
                data = await acp.list_sessions(
                    tenant_id=tenant_id, cwd=cwd, cursor=cursor, route_prefix=route_prefix
                )
            except ApiError:
                return None
            for s in (data or {}).get("sessions") or []:
                if str(s.get("session_id") or "") == acp_session_id:
                    return str(s.get("title") or "").strip() or None
            cursor = (data or {}).get("next_cursor") or ""
            if not cursor:
                return None
        return None

    def _stored_retrieval_refs(self, turn_id: str) -> list[dict]:
        turn = self.repo.get_turn(turn_id)
        return turn.retrievalRefs if turn is not None else []

    def _finalize(
        self,
        turn_id: str,
        parts: list[str],
        stop_reason: str | None,
        error_message: str | None,
        *,
        reasoning_parts: list[str] | None = None,
        token_usage_session_id: str = "",
        token_usage_previous_snapshot: int = 0,
        token_usage_snapshot: int = 0,
        token_used: int = 0,
        retrieval_refs: list[dict] | None = None,
    ) -> None:
        if error_message is not None:
            status = "failed"
        elif stop_reason == "cancelled":
            status = "cancelled"
        else:
            status = "completed"
        self.repo.finalize_turn(
            turn_id=turn_id,
            status=status,
            response_text="".join(parts),
            reasoning_text="".join(reasoning_parts or []),
            stop_reason=stop_reason,
            error_message=error_message,
            token_usage_session_id=token_usage_session_id,
            token_usage_previous_snapshot=token_usage_previous_snapshot,
            token_usage_snapshot=token_usage_snapshot,
            token_used=token_used,
            retrieval_refs=retrieval_refs,
            completed_at=_now_iso(),
        )
        self.connection.commit()
        try:
            self.credits.settle_turn(turn_id)
        except Exception:
            self.connection.rollback()
            logger.exception("Credit settlement failed for turn %s", turn_id)

    def fail_reserved_turn(self, turn_id: str, error_message: str) -> None:
        """Persist a pre-stream failure while preserving the original HTTP error response."""
        self._finalize(turn_id, [], None, error_message)

    def preview_citation(
        self, principal: Principal, turn_id: str, citation_id: str
    ) -> CitationPreviewResponse:
        """Return the durable hit snapshot behind a citation.

        The hit text is stored on the Turn, so history remains explainable after a Document is
        renamed or deleted. Original bytes are handled by download_citation, which re-authorizes
        the Turn owner and resolves the exact immutable source SHA before minting a URL.
        """
        reference = self._citation_reference(principal, turn_id, citation_id)
        hit_text = _public_hit_text(reference) or ""
        public_locator = _public_locator(reference)
        return CitationPreviewResponse(
            citationId=citation_id,
            knowledgeBaseId=str(reference.get("knowledgeBaseId") or ""),
            knowledgeBaseName=str(reference.get("knowledgeBaseName") or ""),
            documentId=str(reference.get("documentId") or ""),
            fileName=str(reference.get("fileName") or ""),
            pageNumber=_positive_locator_number(public_locator.get("pageNumber")),
            hitText=hit_text,
            locator=public_locator,
            previewType="text" if hit_text else "unsupported",
            content=hit_text or None,
            mimeType=(
                str(reference["mimeType"]) if reference.get("mimeType") is not None else None
            ),
        )

    def download_citation(
        self, principal: Principal, turn_id: str, citation_id: str
    ) -> CitationDownloadResponse:
        """Mint a URL for the exact immutable source captured by the Turn citation."""
        reference = self._citation_reference(principal, turn_id, citation_id)
        document_id = str(reference.get("documentId") or "")
        expected_sha256 = str(reference.get("sourceSha") or reference.get("sourceSha256") or "")
        source = DocumentRepository(self.connection).get_citation_source(
            document_id, expected_sha256
        )
        if source is None:
            raise ApiError(404, "CHAT_CITATION_SOURCE_NOT_FOUND", "Citation source not found")
        if expected_sha256 and str(source.get("source_sha256") or "") != expected_sha256:
            raise ApiError(
                409,
                "CHAT_CITATION_SOURCE_MISMATCH",
                "Citation source no longer matches the captured immutable object.",
            )
        if self.library is None:
            raise ApiError(503, "LIBRARY_UNCONFIGURED", "Object storage is not configured")
        ttl = timedelta(seconds=self.settings.presigned_url_ttl_seconds)
        response_headers = (
            {"response-content-type": str(source["mime_type"])} if source.get("mime_type") else None
        )
        return CitationDownloadResponse(
            citationId=citation_id,
            fileName=str(reference.get("fileName") or source["file_name"]),
            downloadUrl=self.library.store.presigned_get_url(
                str(source["source_storage_key"]),
                expires=ttl,
                response_headers=response_headers,
            ),
            expiresAt=(datetime.now(UTC) + ttl).isoformat(),
        )

    def _citation_reference(self, principal: Principal, turn_id: str, citation_id: str) -> dict:
        self._require_turn(principal, turn_id)
        turn = self.repo.get_turn(turn_id)
        if turn is not None:
            for reference in turn.retrievalRefs:
                if str(reference.get("citationId") or "") == citation_id:
                    return reference
        raise ApiError(404, "CHAT_CITATION_NOT_FOUND", "Citation not found")

    async def resolve_permission(
        self, principal: Principal, permission_id: str, body: ResolvePermissionRequest
    ) -> dict:
        pending = self.repo.get_pending_permission(
            permission_id,
            str(principal.active_tenant_id),
            principal.user_id,
        )
        if pending is None:
            raise ApiError(
                404,
                "CHAT_PERMISSION_NOT_FOUND",
                "Pending permission request not found",
            )
        if pending["status"] != "pending":
            raise ApiError(
                409,
                "CHAT_PERMISSION_ALREADY_RESOLVED",
                "Permission request has already been resolved",
            )
        # ACP requires a concrete outcome discriminator; the request id travels in the body.
        outcome = body.outcome or ("selected" if body.optionId else "cancelled")
        data = await self._require_acp().resolve_permission(
            request_id=permission_id,
            outcome=outcome,
            option_id=body.optionId,
            tenant_id=principal.active_tenant_id,
            route_prefix=str(pending["route_prefix"]),
        )
        self.repo.resolve_pending_permission(permission_id, _now_iso())
        self.connection.commit()
        return data or {"permissionId": permission_id, "status": "resolved"}

    # --- Attachments ----------------------------------------------------------

    def validate_turn_preconditions(
        self, principal: Principal, session_id: str, request: ChatTurnRequest
    ) -> None:
        """Pre-flight a turn before its SSE stream starts.

        Verifies session ownership and §5-authorizes any referenced attachments, so a denial is a
        clean HTTP error rather than an empty 200 stream (the body has already started once the
        first event is yielded). Authorization only -- no object bytes are read here.
        """
        row = self._require_session(principal, session_id)
        file_ids = request.attachmentFileIds or []
        if file_ids and self.library is not None:
            # bind=False: pre-flight only authorizes (an unbound temporary file is allowed as-is);
            # the actual bind happens when the turn runs (_prepare_attachments, bind=True).
            self.library.resolve_turn_attachments(principal, session_id, file_ids, bind=False)
        expert_id = row.get("expert_id")
        if expert_id is not None:
            if str(expert_id) == SYSTEM_DEFAULT_EXPERT_ID:
                raise ApiError(
                    409,
                    "EXPERT_NOT_SELECTABLE",
                    "The system default Expert is not available for Chat",
                )
            self.expert_access.require_access(
                str(principal.active_tenant_id),
                str(expert_id),
            )
        self.credits.ensure_turn_allowed(str(principal.active_tenant_id), user_id=principal.user_id)
        self._prepare_acp_cwd(row)

    def _prepare_attachments(
        self,
        principal: Principal,
        session_id: str,
        request: ChatTurnRequest,
        *,
        turn_id: str,
    ) -> tuple[list[dict], str]:
        """Authorize, snapshot, and capability-deliver a turn's attachments.

        Returns (provenance snapshot, text appended to the runtime input). The snapshot is stored
        on the turn; the appended text carries a short-lived Backend URL per attachment and never
        alters the stored request_text. The URLs themselves are not persisted.
        """
        file_ids = request.attachmentFileIds or []
        if not file_ids:
            return [], ""
        if self.library is None:
            raise ApiError(503, "LIBRARY_UNCONFIGURED", "Library service is not configured")
        # bind=True: the first turn to reference an unbound temporary file binds it to this session.
        records = self.library.resolve_turn_attachments(principal, session_id, file_ids, bind=True)
        snapshot = self.library.attachment_snapshot(records, _now_iso())
        blocks: list[str] = []
        for record in records:
            # Delivery stays behind Backend authorization. The bounded capability is tied to this
            # actor, file and Turn, and every GET re-checks current membership and file state.
            url = self.library.attachment_delivery_url(principal, turn_id, record)
            kind = record.mimeType or "binary"
            blocks.append(
                f"\n\n[Attachment: {record.displayName} ({kind})]\nContent available at: {url}"
            )
        return snapshot, "".join(blocks)

    # --- Ownership guards -----------------------------------------------------

    def _require_session(self, principal: Principal, session_id: str) -> dict:
        row = self.repo.get_session_row(
            str(principal.active_tenant_id), principal.user_id, session_id
        )
        if row is None:
            raise _session_not_found()
        return row

    def _require_turn(self, principal: Principal, turn_id: str) -> dict:
        row = self.repo.get_turn_owner(turn_id)
        if (
            row is None
            or str(row.get("tenant_id")) != str(principal.active_tenant_id)
            or str(row.get("user_id")) != str(principal.user_id)
        ):
            raise ApiError(404, "CHAT_TURN_NOT_FOUND", "Chat turn not found")
        return row


def _match_retrieval_source(reference: dict, candidates: list[dict]) -> dict | None:
    """Resolve an upstream reference without guessing across same-name Documents.

    Accepted identities are the persisted LightRAG id, a document-id path segment, or the stable
    ``docId--version`` basename reserved for versioned artifacts.
    """
    reference_id = str(reference.get("reference_id") or "")
    file_path = str(reference.get("file_path") or "").replace("\\", "/")
    segments = tuple(part for part in file_path.split("/") if part)
    basename = segments[-1] if segments else ""

    strong: dict[str, dict] = {}
    for source in candidates:
        document_id = str(source.get("id") or "")
        lightrag_file_source = str(source.get("lightrag_file_source") or "").replace("\\", "/")
        lightrag_basename = lightrag_file_source.rsplit("/", 1)[-1]
        index_document_id = str(source.get("index_document_id") or "")
        if (
            (reference_id and index_document_id and reference_id == index_document_id)
            or (basename and lightrag_basename and basename == lightrag_basename)
            or document_id in segments
            or basename.startswith(f"{document_id}--")
            or basename.startswith(f"{document_id}__")
        ):
            strong[document_id] = source
    if len(strong) == 1:
        return next(iter(strong.values()))
    if strong:
        return None

    return None


def _reference_chunks(value: object, *, max_total_chars: int = 12_000) -> list[str]:
    """Normalize LightRAG's version-dependent chunk-content shapes."""
    raw_items = value if isinstance(value, list) else [value]
    chunks: list[str] = []
    remaining = max_total_chars
    for item in raw_items:
        text = ""
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            for key in ("content", "text", "chunk_content", "chunkContent"):
                candidate = item.get(key)
                if isinstance(candidate, str):
                    text = candidate
                    break
        text = text.strip()
        if not text or remaining <= 0:
            continue
        bounded = text[:remaining]
        chunks.append(bounded)
        remaining -= len(bounded)
    return chunks


def _bounded_hit_text(chunks: list[str], max_chars: int = 4_000) -> str:
    return "\n\n".join(chunks)[:max_chars]


def _reference_locator(reference: dict, file_type: str) -> dict:
    """Return only locators proven by Backend-authored Docling boundary markers.

    LightRAG reference metadata is external input. The current indexing pipeline writes
    one-based page/slide markers before ingestion, so arbitrary upstream page or chunk fields are
    not promoted into the caller-facing locator.
    """
    locator: dict[str, object] = {"type": file_type}
    content = reference.get("content")
    chunks = _reference_chunks(content)
    proven: list[tuple[str, int]] = []
    for chunk in chunks:
        match = re.search(
            r"<!--\s*expert-source-locator:\s*(page|slide)=(\d+)\s*-->",
            chunk,
            flags=re.IGNORECASE,
        )
        if match is not None:
            proven.append((match.group(1).lower(), int(match.group(2))))
    # A file-level LightRAG reference may contain multiple independently ranked chunks. A page
    # is public only when every chunk carries the same Backend marker; otherwise this reference's
    # location is ambiguous and pageNumber remains null.
    if chunks and len(proven) == len(chunks):
        values = set(proven)
        if len(values) == 1:
            kind, number = next(iter(values))
            if number >= 1:
                public_name = "pageNumber" if kind == "page" else "slideNumber"
                locator[public_name] = number
    return locator


def _has_display_identity(reference: dict) -> bool:
    return all(
        str(reference.get(field) or "").strip()
        for field in ("knowledgeBaseId", "documentId", "fileName")
    )


def _positive_locator_number(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 1 else None


def _public_locator(reference: dict) -> dict:
    stored = reference.get("locator")
    stored = stored if isinstance(stored, dict) else {}
    file_type = str(stored.get("type") or "")
    locator: dict[str, object] = {"type": file_type} if file_type else {}

    # Re-derive from the persisted hit content whenever possible. Older rows did not record an
    # explicit provenance discriminator, but their Backend-authored marker remains verifiable.
    proven = _reference_locator(reference, file_type)
    for field in ("pageNumber", "slideNumber"):
        number = _positive_locator_number(proven.get(field))
        if number is not None:
            locator[field] = number

    if reference.get("locatorProvenance") == "docling-page-break":
        for field in ("pageNumber", "slideNumber"):
            if field in locator:
                continue
            number = _positive_locator_number(stored.get(field))
            if number is not None:
                locator[field] = number
    return locator


def _public_hit_text(reference: dict) -> str | None:
    hit_text = str(reference.get("hitText") or "").strip()
    if not hit_text:
        hit_text = _bounded_hit_text(_reference_chunks(reference.get("content"))).strip()
    if not hit_text:
        return None
    cleaned = re.sub(
        r"<!--\s*expert-source-locator:\s*(?:page|slide)=\d+\s*-->\s*",
        "",
        hit_text,
        flags=re.IGNORECASE,
    ).strip()
    return cleaned or None


def _public_retrieval_sources(references: list[dict]) -> list[dict]:
    """Strip external/index integrity identities and deduplicate display locations."""
    sources: list[dict] = []
    seen: dict[tuple[str, str, int | None], int] = {}
    for reference in references:
        available = _has_display_identity(reference)
        file_name = str(reference.get("fileName") or "").strip()
        if not available:
            file_name = "Source unavailable"
        locator = _public_locator(reference)
        page_number = _positive_locator_number(locator.get("pageNumber"))
        citation_id = str(reference.get("citationId") or "").strip() or None
        citation_ids = [citation_id] if citation_id is not None else []
        source = ChatRetrievalSource(
            citationId=citation_id,
            citationIds=citation_ids,
            knowledgeBaseId=(
                str(reference["knowledgeBaseId"])
                if available and reference.get("knowledgeBaseId") is not None
                else None
            ),
            knowledgeBaseName=(
                str(reference["knowledgeBaseName"])
                if available and reference.get("knowledgeBaseName") is not None
                else None
            ),
            documentId=(
                str(reference["documentId"])
                if available and reference.get("documentId") is not None
                else None
            ),
            fileName=file_name,
            pageNumber=page_number,
            mimeType=(
                str(reference["mimeType"])
                if available and reference.get("mimeType") is not None
                else None
            ),
            hitText=_public_hit_text(reference) if available else None,
            locator=locator if available else {},
            previewUrl=(
                str(reference["previewUrl"])
                if available and reference.get("previewUrl") is not None
                else None
            ),
            downloadUrl=(
                str(reference["downloadUrl"])
                if available and reference.get("downloadUrl") is not None
                else None
            ),
            available=available,
        ).model_dump()

        document_id = source.get("documentId")
        locator_type = str(locator.get("type") or "").lower()
        slide_number = _positive_locator_number(locator.get("slideNumber"))
        key: tuple[str, str, int | None] | None = None
        if document_id and page_number is not None:
            key = (str(document_id), "page", page_number)
        elif document_id and slide_number is not None:
            key = (str(document_id), "slide", slide_number)
        elif document_id and locator_type not in {"pdf", "ppt", "pptx"}:
            key = (str(document_id), "document", None)
        if key is not None and key in seen:
            existing = sources[seen[key]]
            for current_id in citation_ids:
                if current_id not in existing["citationIds"]:
                    existing["citationIds"].append(current_id)
            continue
        if key is not None:
            seen[key] = len(sources)
        sources.append(source)
    return sources


def _sources_payload(references: list[dict], *, already_public: bool = False) -> dict:
    documents = references if already_public else _public_retrieval_sources(references)
    knowledge_base_ids = list(
        dict.fromkeys(
            str(item.get("knowledgeBaseId") or "")
            for item in documents
            if item.get("knowledgeBaseId")
        )
    )
    payload: dict = {
        "documents": documents,
        "knowledgeBaseIds": knowledge_base_ids,
    }
    if len(knowledge_base_ids) == 1:
        payload["knowledgeBaseId"] = knowledge_base_ids[0]
    return payload


def _session_not_found() -> ApiError:
    return ApiError(404, "CHAT_SESSION_NOT_FOUND", "Chat session not found")


def _runtime_identity(row: dict) -> dict[str, str] | None:
    if row.get("expert_id") is None:
        return None
    runtime_type = row.get("runtime_type")
    if runtime_type is None:
        raise ApiError(
            409,
            "CHAT_EXPERT_RUNTIME_INVALID",
            "Chat Session has an incomplete Expert runtime identity",
        )
    return {"expert_id": str(row["expert_id"]), "runtime_type": str(runtime_type)}


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _chat_search_snippet(text: str, keyword: str, max_length: int = 160) -> str:
    match_start = text.casefold().find(keyword.casefold())
    if match_start < 0:
        return text[:max_length]
    if len(text) <= max_length:
        return text

    # A keyword may itself be up to 200 characters. Keep the complete match even when that makes
    # the bounded snippet slightly longer than the normal 160-character target.
    bounded_length = max(max_length, len(keyword) + 2)
    context_length = max(0, bounded_length - len(keyword) - 2)
    start = max(0, match_start - context_length // 2)
    end = min(len(text), match_start + len(keyword) + context_length - (match_start - start))

    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(text) else ""
    remaining = bounded_length - len(prefix) - len(suffix)
    if end - start < remaining:
        start = max(0, end - remaining)
        prefix = "…" if start > 0 else ""
        remaining = bounded_length - len(prefix) - len(suffix)
    end = min(len(text), start + remaining)
    return f"{prefix}{text[start:end]}{suffix}"


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _reasoning_delta_payload(delta: str, turn_id: str | None) -> dict:
    payload = {
        "delta": delta,
        "channel": "reasoning",
        "mode": "append",
        "reasoningId": f"{turn_id or 'pending'}:reasoning",
    }
    if turn_id:
        payload["turnId"] = turn_id
    return payload


def _normalize_answer_markdown(text: str) -> str:
    """Apply deterministic Markdown cleanup to final assistant answers."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return ""

    normalized_lines: list[str] = []
    blank_seen = False
    for raw_line in text.split("\n"):
        line = _normalize_markdown_line(raw_line.rstrip())
        if not line.strip():
            if blank_seen:
                continue
            blank_seen = True
            normalized_lines.append("")
            continue
        blank_seen = False
        normalized_lines.append(line)
    return "\n".join(normalized_lines).strip()


def _normalize_answer_markdown_delta(text: str, *, at_line_start: bool = True) -> str:
    """Normalize Markdown markers without changing streaming whitespace.

    The line-start markers (headings, list bullets) are anchored at the start of a line, so
    they may only be applied to the first line of a streamed chunk when that chunk actually
    begins at a line boundary. Otherwise a mid-line fragment like "#5" would be mangled into
    "# 5". Lines after an embedded newline are always genuine line starts.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    normalized = [
        line if index == 0 and not at_line_start else _normalize_markdown_line(line)
        for index, line in enumerate(lines)
    ]
    return "\n".join(normalized)


def _normalize_markdown_line(line: str) -> str:
    line = re.sub(r"^(#{1,6})(\S)", r"\1 \2", line)
    line = re.sub(r"^(\s*)[\u2022\u25cf]\s+", r"\1- ", line)
    line = re.sub(r"^(\s*)[-*+]\s+", r"\1- ", line)
    line = re.sub(r"^(\s*)(\d+)[)\uff09\u3001]\s*", r"\1\2. ", line)
    return line


class _CredentialRedactor:
    """Hide a current Turn capability even if the model echoes it across token chunks."""

    def __init__(self, secret: str) -> None:
        self.secret = secret
        self.pending = ""

    def push(self, text: str) -> str:
        if not self.secret:
            return text
        combined = (self.pending + text).replace(self.secret, "[redacted]")
        self.pending = ""
        for length in range(min(len(combined), len(self.secret) - 1), 0, -1):
            if combined.endswith(self.secret[:length]):
                self.pending = combined[-length:]
                return combined[:-length]
        return combined

    def finish(self) -> str:
        tail, self.pending = self.pending, ""
        return "[redacted]" if len(tail) > 12 else tail


class _SmoothTextBuffer:
    def __init__(self, *, max_chars: int, punctuation: bool = False) -> None:
        self.max_chars = max_chars
        self.punctuation = punctuation
        self._text = ""
        # Whether the chunk most recently returned by push()/flush() began at a line start.
        # The very first chunk does; afterwards a chunk is a line start only when the previous
        # one ended on a newline.
        self.chunk_at_line_start = True
        self._next_at_line_start = True

    def push(self, delta: str) -> str | None:
        self._text += delta
        split_at = self._split_index()
        if split_at is None:
            return None
        chunk = self._text[:split_at]
        self._text = self._text[split_at:]
        self._mark(chunk)
        return chunk

    def flush(self) -> str:
        chunk = self._text
        self._text = ""
        self._mark(chunk)
        return chunk

    def _mark(self, chunk: str) -> None:
        self.chunk_at_line_start = self._next_at_line_start
        if chunk:
            self._next_at_line_start = chunk.endswith("\n")

    def _split_index(self) -> int | None:
        if not self._text:
            return None
        newline = self._text.rfind("\n")
        if newline >= 0:
            return newline + 1
        if self.punctuation:
            for index in range(len(self._text) - 1, -1, -1):
                if _is_soft_flush_char(self._text[index]) and index + 1 >= 12:
                    return index + 1
        if len(self._text) >= self.max_chars:
            return len(self._text)
        return None


def _is_soft_flush_char(char: str) -> bool:
    return char in {
        " ",
        ".",
        "!",
        "?",
        ";",
        ":",
        "\u3002",
        "\uff01",
        "\uff1f",
        "\uff1b",
        "\uff1a",
        "\uff0c",
        "\u3001",
    }


_ACP_REASONING_EVENTS = frozenset({"reasoning", "tool_call", "usage"})


def _log_acp_tool_failure(
    data: dict, *, session_id: str, turn_id: str, expert_id: str,
) -> None:
    payload = data.get("data")
    if not isinstance(payload, dict) or payload.get("status") != "failed":
        return
    kind = payload.get("kind")
    action = kind if kind in {"read", "edit", "delete", "execute", "search", "fetch"} else "tool"
    # Only structured execution failures are events. Never log raw inputs, outputs,
    # tool titles, signed URLs or natural-language model refusals.
    logger.warning(
        "ACP tool failure session=%s turn=%s expert=%s action=%s result=failed reason=tool_failed",
        session_id, turn_id, expert_id, action,
    )


_PUBLIC_PROGRESS = "Processing your request.\n"
_PUBLIC_OPERATION_FAILED = "A requested operation could not be completed.\n"


def _public_reasoning(text: str | None) -> str:
    """Legacy reasoning is private; expose only application-owned progress."""
    if not text:
        return ""
    if all(line + "\n" in {_PUBLIC_PROGRESS, _PUBLIC_OPERATION_FAILED}
           for line in text.splitlines()):
        return text
    return _PUBLIC_PROGRESS


def _acp_reasoning_text(event: str, data: dict) -> str | None:
    """Publish business progress, never raw agent reasoning or tool metadata."""
    if event == "tool_call":
        payload = data.get("data")
        if isinstance(payload, dict) and payload.get("status") == "failed":
            return _PUBLIC_OPERATION_FAILED
        return _PUBLIC_PROGRESS
    if event == "reasoning":
        return _PUBLIC_PROGRESS
    return None


def _acp_token_used(data: dict) -> int | None:
    """Extract the ACP absolute context-window usage from a gateway event."""
    usage = data.get("data")
    if not isinstance(usage, dict):
        usage = data
    value = usage.get("used")
    if isinstance(value, bool):
        return None
    try:
        token_used = int(value)
    except (TypeError, ValueError):
        return None
    return token_used if token_used >= 0 else None


def _friendly_acp_error_message(message: str | None, details: dict | None = None) -> str:
    raw_message = str(message or "").strip()
    haystack_parts = [raw_message.lower()]
    if details:
        try:
            haystack_parts.append(json.dumps(details, ensure_ascii=False).lower())
        except TypeError:
            pass
    haystack = " ".join(part for part in haystack_parts if part)
    if (
        "token_invalidated" in haystack
        or "tokeninvalidated" in haystack
        or "authentication token has been invalidated" in haystack
        or ("session/prompt" in haystack and "acp error -32603" in haystack)
        or ("401" in haystack and "unauthorized" in haystack and "session/prompt" in haystack)
    ):
        return "The service connection has expired. Please try again later."
    return "The requested operation could not be completed. Please try again."


@dataclass
class _AcpRoute:
    route_prefix: str
    search_mode: str
    session_id: str | None
    session_column: str
    uses_service_defaults: bool = False
    thread_id: str = ""


@dataclass
class _AcpTurnResult:
    parts: list[str] | None = None
    reasoning_parts: list[str] | None = None
    stop_reason: str | None = None
    error_message: str | None = None
    bound_session_id: str | None = None
    saw_delta: bool = False
    saw_done: bool = False
    previous_usage_snapshot: int | None = None
    usage_current: int | None = None

    def __post_init__(self) -> None:
        if self.parts is None:
            self.parts = []
        if self.reasoning_parts is None:
            self.reasoning_parts = []

    def capture_usage(self, used: int) -> None:
        # A pooled instance may replay the prior snapshot before emitting the live one. A loaded
        # instance emits only the live value. Keeping the latest event works for both paths.
        self.usage_current = used

    def bind_session(self, session_id: str) -> None:
        if session_id != self.bound_session_id:
            self.bound_session_id = session_id
            self.previous_usage_snapshot = None

    @property
    def token_used(self) -> int:
        if self.usage_current is None:
            return 0
        if self.previous_usage_snapshot is None:
            return self.usage_current
        return max(self.usage_current - self.previous_usage_snapshot, 0)

    @property
    def previous_usage_size(self) -> int:
        return max(self.previous_usage_snapshot or 0, 0)

    @property
    def token_usage_snapshot(self) -> int:
        return self.usage_current or 0

from __future__ import annotations

import json
from typing import Any

from app.db import DatabaseConnection
from app.domain.chat import ChatSearchScope, ChatSession, ChatTurn
from app.services._sql import execute, fetch_all, fetch_one, json_load, json_param, rowcount


class ChatRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    # --- Sessions -------------------------------------------------------------

    def create_session(
        self,
        *,
        session_id: str,
        tenant_id: str,
        user_id: str,
        title: str | None,
        agent_options: dict[str, Any],
        runtime_identity: dict[str, str] | None,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into chat_sessions (
                id, tenant_id, user_id, title, agent_options,
                expert_id, runtime_type,
                status, is_pinned, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, 'active', false, ?, ?)
            """,
            (
                session_id,
                tenant_id,
                user_id,
                title,
                json_param(self.connection, agent_options),
                (runtime_identity or {}).get("expert_id"),
                (runtime_identity or {}).get("runtime_type"),
                now,
                now,
            ),
        )

    def get_session_row(
        self, tenant_id: str, user_id: str, session_id: str
    ) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select * from chat_sessions
            where id = ? and tenant_id = ? and user_id = ? and deleted_at is null
            limit 1
            """,
            (session_id, tenant_id, user_id),
        )

    def get_session(self, tenant_id: str, user_id: str, session_id: str) -> ChatSession | None:
        row = self.get_session_row(tenant_id, user_id, session_id)
        return _map_session(row) if row is not None else None

    def list_sessions(
        self, tenant_id: str, user_id: str, status: str = "active"
    ) -> list[ChatSession]:
        rows = fetch_all(
            self.connection,
            """
            select * from chat_sessions
            where tenant_id = ? and user_id = ? and status = ? and deleted_at is null
            order by is_pinned desc, pinned_at desc, updated_at desc
            """,
            (tenant_id, user_id, status),
        )
        return [_map_session(row) for row in rows]

    def search_sessions(
        self,
        *,
        tenant_id: str,
        user_id: str,
        keyword: str,
        scope: ChatSearchScope,
        limit: int,
        offset: int,
    ) -> tuple[list[dict[str, Any]], int]:
        pattern = f"%{_escape_like(keyword.casefold())}%"
        question_match = "lower(t.request_text) like p.pattern escape '\\'"
        answer_match = (
            "t.response_text is not null and lower(t.response_text) like p.pattern escape '\\'"
        )
        title_match = "s.title is not null and lower(s.title) like p.pattern escape '\\'"
        if scope == "question":
            match_condition = question_match
            matched_type = "'question'"
            matched_text = "t.request_text"
        elif scope == "answer":
            match_condition = answer_match
            matched_type = "'answer'"
            matched_text = "t.response_text"
        else:
            # A renamed session can have no turns matching its new title (or no turns at all).
            # Keep the title in the default "all" search scope and use a LEFT JOIN below so
            # such sessions are discoverable instead of being eliminated by the turn join.
            match_condition = f"({title_match} or {question_match} or {answer_match})"
            matched_type = (
                f"case when {title_match} then 'title' "
                f"when {question_match} then 'question' else 'answer' end"
            )
            matched_text = (
                f"case when {title_match} then s.title "
                f"when {question_match} then t.request_text else t.response_text end"
            )

        # Title matches must not require a turn. Question/answer-only searches retain the
        # inner join, while the default scope preserves sessions that only match by title.
        join = (
            "left join chat_turns t on t.session_id = s.id "
            "and t.tenant_id = ? and t.user_id = ? and t.is_internal = false"
            if scope == "all"
            else "join chat_turns t on t.session_id = s.id"
        )
        turn_where = "" if scope == "all" else "and t.tenant_id = ? and t.user_id = ? and t.is_internal = false"
        ownership_params = (
            (tenant_id, user_id, pattern, tenant_id, user_id)
            if scope == "all"
            else (pattern, tenant_id, user_id, tenant_id, user_id)
        )
        total_row = fetch_one(
            self.connection,
            f"""
            select count(distinct s.id) as count
            from chat_sessions s
            {join}
            cross join (select ? as pattern) p
            where s.tenant_id = ?
              and s.user_id = ?
              and s.status = 'active'
              and s.deleted_at is null
              {turn_where}
              and ({match_condition})
            """,
            ownership_params,
        )
        rows = fetch_all(
            self.connection,
            f"""
            with ranked_matches as (
              select
                s.id as session_id,
                s.title,
                s.updated_at as session_updated_at,
                coalesce(t.id, '') as matched_turn_id,
                {matched_type} as matched_type,
                {matched_text} as matched_text,
                row_number() over (
                  partition by s.id
                  order by t.created_at desc, t.id desc
                ) as match_rank
              from chat_sessions s
              {join}
              cross join (select ? as pattern) p
              where s.tenant_id = ?
                and s.user_id = ?
                and s.status = 'active'
                and s.deleted_at is null
                {turn_where}
                and ({match_condition})
            )
            select
              session_id, title, matched_turn_id, matched_type, matched_text
            from ranked_matches
            where match_rank = 1
            order by session_updated_at desc, session_id desc
            limit ? offset ?
            """,
            (*ownership_params, limit, offset),
        )
        total = int(total_row["count"] if total_row else 0)
        return rows, total

    def update_session_title(self, session_id: str, title: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update chat_sessions
            set title = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (title, now, session_id),
        )
        return rowcount(cursor) > 0

    def set_acp_session_id(self, session_id: str, acp_session_id: str | None, now: str) -> bool:
        cursor = execute(
            self.connection,
            "update chat_sessions set acp_session_id = ?, updated_at = ? where id = ?",
            (acp_session_id, now, session_id),
        )
        return rowcount(cursor) > 0

    def isolate_session_workspace(self, row: dict[str, Any], now: str) -> None:
        options = json_load(row["agent_options"])
        execute(
            self.connection,
            """
            update chat_sessions
            set agent_options = ?, acp_session_id = null, acp_search_session_id = null,
                updated_at = ?
            where id = ? and agent_options = ? and deleted_at is null
            """,
            (
                json_param(self.connection, {**options, "workspaceScope": "user"}),
                now,
                row["id"],
                row["agent_options"]
                if isinstance(row["agent_options"], str)
                else json_param(self.connection, options),
            ),
        )

    def set_acp_search_session_id(
        self, session_id: str, acp_session_id: str | None, now: str
    ) -> bool:
        cursor = execute(
            self.connection,
            "update chat_sessions set acp_search_session_id = ?, updated_at = ? where id = ?",
            (acp_session_id, now, session_id),
        )
        return rowcount(cursor) > 0

    def set_session_pin(
        self, session_id: str, is_pinned: bool, pinned_at: str | None, now: str
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            update chat_sessions
            set is_pinned = ?, pinned_at = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (is_pinned, pinned_at, now, session_id),
        )
        return rowcount(cursor) > 0

    def set_session_status(self, session_id: str, status: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update chat_sessions
            set status = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (status, now, session_id),
        )
        return rowcount(cursor) > 0

    def delete_session(self, session_id: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update chat_sessions
            set deleted_at = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (now, now, session_id),
        )
        return rowcount(cursor) > 0

    # --- Turns ----------------------------------------------------------------

    def create_turn(
        self,
        *,
        turn_id: str,
        session_id: str,
        tenant_id: str,
        user_id: str,
        request_text: str,
        model: str | None,
        query_rewrite: bool,
        multi_hop_config: dict[str, Any] | None,
        token_usage_scope: str,
        runtime_identity: dict[str, str] | None,
        now: str,
        attachments: list[dict] | None = None,
    ) -> None:
        execute(
            self.connection,
            """
            insert into chat_turns (
                id, session_id, tenant_id, user_id, request_text, model,
                query_rewrite, multi_hop_config, status,
                token_usage_scope, expert_id, runtime_type,
                is_internal, attachments, created_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?, false, ?, ?)
            """,
            (
                turn_id,
                session_id,
                tenant_id,
                user_id,
                request_text,
                model,
                query_rewrite,
                json_param(self.connection, multi_hop_config)
                if multi_hop_config is not None
                else None,
                token_usage_scope,
                (runtime_identity or {}).get("expert_id"),
                (runtime_identity or {}).get("runtime_type"),
                json_param(self.connection, attachments or []),
                now,
            ),
        )

    def get_token_usage_baseline(
        self,
        *,
        session_id: str,
        tenant_id: str,
        user_id: str,
        token_usage_scope: str,
        token_usage_session_id: str,
    ) -> int | None:
        """Return the latest final snapshot for one ACP session and usage scope."""
        latest = fetch_one(
            self.connection,
            """
            select token_usage_snapshot
            from chat_turns
            where session_id = ?
              and tenant_id = ?
              and user_id = ?
              and token_usage_scope = ?
              and token_usage_session_id = ?
              and status = 'completed'
              and token_usage_snapshot > 0
            order by completed_at desc, created_at desc, id desc
            limit 1
            """,
            (
                session_id,
                tenant_id,
                user_id,
                token_usage_scope,
                token_usage_session_id,
            ),
        )
        if latest is not None:
            return int(latest["token_usage_snapshot"])
        # Pre-v2 rows have no durable ACP session id, so they cannot prove the required same-session
        # boundary. The first v2 Turn after upgrade therefore starts from a zero baseline.
        return None

    def update_turn_attachments(self, turn_id: str, attachments: list[dict]) -> None:
        execute(
            self.connection,
            "update chat_turns set attachments = ? where id = ? and status = 'running'",
            (json_param(self.connection, attachments), turn_id),
        )

    def update_turn_retrieval_refs(self, turn_id: str, retrieval_refs: list[dict]) -> None:
        """Persist retrieved sources before ACP starts so citation links are resolvable."""
        execute(
            self.connection,
            "update chat_turns set retrieval_refs = ? where id = ? and status = 'running'",
            (json_param(self.connection, retrieval_refs), turn_id),
        )

    def finalize_turn(
        self,
        *,
        turn_id: str,
        status: str,
        response_text: str,
        reasoning_text: str,
        stop_reason: str | None,
        error_message: str | None,
        token_usage_session_id: str,
        token_usage_previous_snapshot: int,
        token_usage_snapshot: int,
        token_used: int,
        retrieval_refs: list[dict] | None = None,
        completed_at: str,
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            update chat_turns
            set status = ?, response_text = ?, reasoning_text = ?, stop_reason = ?, error_message = ?,
                token_usage_session_id = ?, token_usage_previous_snapshot = ?,
                token_usage_snapshot = ?, token_used = ?, retrieval_refs = ?, completed_at = ?
            where id = ? and status = 'running'
            """,
            (
                status,
                response_text,
                reasoning_text,
                stop_reason,
                error_message,
                token_usage_session_id,
                token_usage_previous_snapshot,
                token_usage_snapshot,
                token_used,
                json_param(self.connection, retrieval_refs or []),
                completed_at,
                turn_id,
            ),
        )
        return rowcount(cursor) > 0

    def append_event(self, turn_id: str, event: str, payload: dict) -> int:
        # Sequence allocation, event insertion and visible progress share one transaction.
        row = fetch_one(
            self.connection,
            "update chat_turns set event_seq = event_seq + 1 where id = ? returning event_seq",
            (turn_id,),
        )
        seq = int(row["event_seq"])
        if event == "turn_state":
            payload = {**payload, "eventSeq": seq}
        execute(
            self.connection,
            "insert into chat_turn_events (turn_id, seq, event, payload) values (?, ?, ?, ?)",
            (turn_id, seq, event, json_param(self.connection, payload)),
        )
        column = {"message_delta": "response_text", "reasoning_delta": "reasoning_text"}.get(event)
        if column:
            execute(
                self.connection,
                f"update chat_turns set {column} = coalesce({column}, '') || ? "
                "where id = ? and status = 'running'",
                (str(payload.get("delta") or ""), turn_id),
            )
        return seq

    def list_events(self, turn_id: str, after: int) -> list[dict]:
        rows = fetch_all(
            self.connection,
            "select seq, event, payload from chat_turn_events "
            "where turn_id = ? and seq > ? order by seq limit 200",
            (turn_id, after),
        )
        return [{**row, "payload": json_load(row["payload"])} for row in rows]

    def interrupt_running_turns(self, now: str) -> list[str]:
        rows = fetch_all(
            self.connection,
            "update chat_turns set status = 'failed', stop_reason = 'interrupted', "
            "error_message = 'Chat execution was interrupted by a Backend restart', "
            "completed_at = ? where status = 'running' returning id",
            (now,),
        )
        return [str(row["id"]) for row in rows]

    def get_turn_owner(self, turn_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select t.id, t.session_id, t.tenant_id, t.user_id, t.status
            from chat_turns t
            join chat_sessions s on s.id = t.session_id
            where t.id = ? and s.deleted_at is null
            limit 1
            """,
            (turn_id,),
        )

    def get_turn(self, turn_id: str) -> ChatTurn | None:
        row = fetch_one(
            self.connection, "select * from chat_turns where id = ? limit 1", (turn_id,)
        )
        return _map_turn(row) if row is not None else None

    def cancel_running_turn(self, turn_id: str, completed_at: str) -> bool:
        cursor = execute(
            self.connection,
            "update chat_turns set status = 'cancelled', completed_at = ? where id = ? and status = 'running'",
            (completed_at, turn_id),
        )
        return rowcount(cursor) > 0

    def list_turns(self, session_id: str) -> list[ChatTurn]:
        rows = fetch_all(
            self.connection,
            "select * from chat_turns where session_id = ? order by created_at asc",
            (session_id,),
        )
        return [_map_turn(row) for row in rows]

    def list_kb_ids_for_expert(self, expert_id: str) -> list[str]:
        """Knowledge bases attached to an expert (retrieval scope for bound chat sessions).

        Only active, non-deleted KBs count: an archived or soft-deleted base stops being
        retrieved without touching the chat session. Knowledge bases stay platform-owned --
        the tenant reaches them exclusively through the expert they are entitled to.
        """
        rows = fetch_all(
            self.connection,
            """
            select kb.id
            from knowledge_bases kb
            join expert_knowledge_bases ekb on ekb.knowledge_base_id = kb.id
            join knowledge_base_lightrag_instances li on li.knowledge_base_id = kb.id
            where ekb.expert_id = ?
              and kb.deleted_at is null
              and kb.status = 'active'
              and kb.index_status = 'ready'
              and (li.status = 'ready' or li.status is null)
            order by kb.created_at asc, kb.id asc
            """,
            (expert_id,),
        )
        return [str(row["id"]) for row in rows]

    def knowledge_binding_states(self, expert_id: str) -> list[dict]:
        return fetch_all(
            self.connection,
            """
            select kb.id as knowledge_base_id, kb.status as knowledge_base_status,
                   kb.deleted_at as knowledge_base_deleted_at,
                   kb.index_status, kb.index_error,
                   li.status as binding_status, li.workspace, li.base_url
            from expert_knowledge_bases ekb
            join knowledge_bases kb on kb.id = ekb.knowledge_base_id
            left join knowledge_base_lightrag_instances li
              on li.knowledge_base_id = kb.id
            where ekb.expert_id = ?
            order by kb.id
            """,
            (expert_id,),
        )

    def save_pending_permission(
        self,
        *,
        permission_id: str,
        session_id: str,
        tenant_id: str,
        user_id: str,
        route_prefix: str,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into chat_pending_permissions (
              id, session_id, tenant_id, user_id, route_prefix, status, created_at
            )
            values (?, ?, ?, ?, ?, 'pending', ?)
            on conflict (id) do update set
              session_id = excluded.session_id,
              tenant_id = excluded.tenant_id,
              user_id = excluded.user_id,
              route_prefix = excluded.route_prefix
            """,
            (permission_id, session_id, tenant_id, user_id, route_prefix, now),
        )

    def get_pending_permission(
        self,
        permission_id: str,
        tenant_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select id, session_id, route_prefix, status
            from chat_pending_permissions
            where id = ? and tenant_id = ? and user_id = ?
            limit 1
            """,
            (permission_id, tenant_id, user_id),
        )

    def resolve_pending_permission(self, permission_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update chat_pending_permissions
            set status = 'resolved', resolved_at = ?
            where id = ? and status = 'pending'
            """,
            (now, permission_id),
        )


def _map_session(row: dict[str, Any]) -> ChatSession:
    return ChatSession(
        id=str(row["id"]),
        title=str(row["title"]) if row.get("title") is not None else None,
        status=str(row.get("status", "active")),
        isPinned=bool(row.get("is_pinned")),
        expertId=str(row["expert_id"]) if row.get("expert_id") is not None else None,
        runtimeType=(str(row["runtime_type"]) if row.get("runtime_type") is not None else None),
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )


def _map_turn(row: dict[str, Any]) -> ChatTurn:
    return ChatTurn(
        id=str(row["id"]),
        sessionId=str(row["session_id"]),
        requestText=str(row["request_text"]),
        reasoningText=str(row["reasoning_text"]) if row.get("reasoning_text") is not None else None,
        eventSeq=int(row.get("event_seq") or 0),
        responseText=str(row["response_text"]) if row.get("response_text") is not None else None,
        model=str(row["model"]) if row.get("model") is not None else None,
        expertId=str(row["expert_id"]) if row.get("expert_id") is not None else None,
        runtimeType=(str(row["runtime_type"]) if row.get("runtime_type") is not None else None),
        status=str(row["status"]),
        stopReason=str(row["stop_reason"]) if row.get("stop_reason") is not None else None,
        errorMessage=str(row["error_message"]) if row.get("error_message") is not None else None,
        attachments=_load_attachment_list(row.get("attachments")),
        retrievalRefs=_load_attachment_list(row.get("retrieval_refs")),
        createdAt=str(row["created_at"]),
        completedAt=str(row["completed_at"]) if row.get("completed_at") is not None else None,
    )


def _load_attachment_list(value: Any) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(parsed, list):
            return parsed
    return []


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

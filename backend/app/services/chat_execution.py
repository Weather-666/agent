"""Single-process Turn execution; browser connections only subscribe to durable events."""
from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import datetime, timezone

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import open_database_connection
from app.domain.auth import Principal
from app.services.chat_repository import ChatRepository
from app.services.chat_service import ChatService, _public_reasoning, _public_retrieval_sources
from app.services.credit_service import CreditService

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _frame(event: str, payload: dict, seq: int) -> str:
    return f"id: {seq}\nevent: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _snapshot(turn) -> dict:
    value = turn.model_dump()
    value["turnId"] = turn.id
    value["reasoningText"] = _public_reasoning(turn.reasoningText)
    value["retrievalRefs"] = _public_retrieval_sources(turn.retrievalRefs)
    return value


class ChatExecution:
    """One application worker owns all live upstream streams.

    The database is the source of truth for replay, ownership and settlement. Do not
    run multiple Backend workers until execution ownership is coordinated across them.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tasks: dict[str, asyncio.Task] = {}
        self.stopping = False

    def recover(self) -> None:
        with open_database_connection(self.settings) as connection:
            repo = ChatRepository(connection)
            for turn_id in repo.interrupt_running_turns(_now()):
                payload = _snapshot(repo.get_turn(turn_id))
                payload["code"] = "CHAT_TURN_INTERRUPTED"
                repo.append_event(turn_id, "turn_state", payload)
                CreditService(connection, self.settings).settle_turn(turn_id)
            connection.commit()

    def start(self, turn_id: str, factory, principal, session_id, body) -> None:
        self.tasks[turn_id] = asyncio.create_task(
            self._run(turn_id, factory, principal, session_id, body),
            name=f"chat:{turn_id}",
        )

    async def _run(self, turn_id, factory, principal, session_id, body) -> None:
        with open_database_connection(self.settings) as connection:
            service: ChatService = factory(connection)
            repo = service.repo
            try:
                async with aclosing(service.stream_turn(
                    principal, session_id, body, turn_id=turn_id
                )) as stream:
                    async for frame in stream:
                        lines = frame.splitlines()
                        event = next(line[7:] for line in lines if line.startswith("event: "))
                        payload = json.loads(
                            next(line[6:] for line in lines if line.startswith("data: "))
                        )
                        repo.append_event(turn_id, event, payload)
                        connection.commit()
            except asyncio.CancelledError:
                # Cancellation here comes only from the explicit stop API or shutdown.
                turn = repo.get_turn(turn_id)
                if turn and turn.status == "running":
                    service._finalize(
                        turn_id, [turn.responseText or ""], "cancelled", None,
                        reasoning_parts=[turn.reasoningText or ""],
                        retrieval_refs=turn.retrievalRefs,
                    )
            except Exception:
                connection.rollback()
                logger.exception("Background Chat Turn failed: %s", turn_id)
                turn = repo.get_turn(turn_id)
                if turn and turn.status == "running":
                    service._finalize(
                        turn_id, [turn.responseText or ""], None,
                        "Chat turn failed unexpectedly. Please retry.",
                        reasoning_parts=[turn.reasoningText or ""],
                        retrieval_refs=turn.retrievalRefs,
                    )
            finally:
                turn = repo.get_turn(turn_id)
                if turn:
                    if self.stopping and turn.status == "cancelled":
                        from app.services._sql import execute
                        execute(
                            connection,
                            "update chat_turns set status = 'failed', stop_reason = 'interrupted', "
                            "error_message = 'Chat execution was interrupted by Backend shutdown' "
                            "where id = ?",
                            (turn_id,),
                        )
                        turn = repo.get_turn(turn_id)
                    payload = _snapshot(turn)
                    if turn.stopReason == "interrupted":
                        payload["code"] = "CHAT_TURN_INTERRUPTED"
                    repo.append_event(turn_id, "turn_state", payload)
                    connection.commit()
                self.tasks.pop(turn_id, None)

    def validate_cursor(self, principal: Principal, turn_id: str, after: int | None) -> None:
        with open_database_connection(self.settings) as connection:
            service = ChatService(connection, settings=self.settings)
            service._require_turn(principal, turn_id)
            turn = service.repo.get_turn(turn_id)
            if after is not None and after > turn.eventSeq:
                raise ApiError(400, "CHAT_EVENT_CURSOR_INVALID", "Event cursor is ahead of the Turn")

    async def events(
        self, principal: Principal, turn_id: str, after: int | None
    ) -> AsyncIterator[str]:
        cursor = after
        while True:
            # Never keep a DB transaction or request-scoped connection across a network yield.
            with open_database_connection(self.settings) as connection:
                service = ChatService(connection, settings=self.settings)
                service._require_turn(principal, turn_id)
                repo = service.repo
                turn = repo.get_turn(turn_id)
                if cursor is None or (
                    cursor == 0 and turn.eventSeq == 0 and turn.status != "running"
                ):
                    cursor = turn.eventSeq
                    snapshot = _frame("turn_snapshot", _snapshot(turn), cursor)
                else:
                    snapshot = None
                rows = repo.list_events(turn_id, cursor)
                terminal = turn.status != "running" and turn_id not in self.tasks
            if snapshot is not None:
                yield snapshot
            for row in rows:
                cursor = int(row["seq"])
                payload = dict(row["payload"])
                if row["event"] == "reasoning_delta":
                    payload["delta"] = _public_reasoning(payload.get("delta"))
                elif row["event"] in {"turn_state", "turn_snapshot"}:
                    payload["reasoningText"] = _public_reasoning(payload.get("reasoningText"))
                yield _frame(str(row["event"]), payload, cursor)
            if terminal and (not rows or cursor >= turn.eventSeq):
                return
            if not rows:
                await asyncio.sleep(0.1)

    async def cancel(self, principal: Principal, turn_id: str) -> dict:
        self.validate_cursor(principal, turn_id, None)
        task = self.tasks.get(turn_id)
        if task is not None:
            task.cancel()
            # A disconnect of the cancel request must not interrupt cancellation cleanup.
            await asyncio.shield(task)
        with open_database_connection(self.settings) as connection:
            turn = ChatRepository(connection).get_turn(turn_id)
            return {"turnId": turn_id, "status": turn.status}

    async def close(self) -> None:
        self.stopping = True
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

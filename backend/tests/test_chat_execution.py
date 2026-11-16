import asyncio
import json
from contextlib import aclosing

import pytest

from app.db import open_database_connection
from app.domain.chat import ChatTurnRequest, CreateSessionRequest
from app.services.chat_execution import ChatExecution
from app.services.chat_repository import ChatRepository
from app.services.chat_service import ChatService, _CredentialRedactor
from app.services.library_service import LibraryService
from test_app import FakeAcpGatewayClient, FakeObjectStore
from test_expert_runtime import _prepare_database, _principal
from test_library_team import _settings


class GatedAcp(FakeAcpGatewayClient):
    def __init__(self):
        super().__init__()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.calls = 0

    def stream_turn(self, **kwargs):
        async def stream():
            self.calls += 1
            try:
                for event, payload in [
                    ("session", {"session_id": "gated-session"}),
                    ("delta", {"text": "Progress before disconnect. " * 8}),
                ]:
                    yield f"event: {event}"
                    yield "data: " + json.dumps(payload)
                    yield ""
                await self.release.wait()
                for event, payload in [
                    ("delta", {"text": "Final answer after reconnect."}),
                    ("usage", {"data": {"used": 123}}),
                    ("done", {"stop_reason": "end_turn"}),
                ]:
                    yield f"event: {event}"
                    yield "data: " + json.dumps(payload)
                    yield ""
            finally:
                self.closed.set()
        return stream()


def decode(frame):
    lines = frame.splitlines()
    return (
        int(next(line[4:] for line in lines if line.startswith("id: "))),
        next(line[7:] for line in lines if line.startswith("event: ")),
        json.loads(next(line[6:] for line in lines if line.startswith("data: "))),
    )


async def reserve(settings, acp):
    with open_database_connection(settings) as connection:
        service = ChatService(connection, acp=acp, settings=settings)
        session = await service.create_session(_principal(), CreateSessionRequest())
        body = ChatTurnRequest(question="Keep working after disconnect")
        turn_id = service.reserve_turn(_principal(), session.id, body)
    return session.id, turn_id, body


@pytest.mark.asyncio
async def test_disconnect_snapshot_replay_cancel_and_restart(tmp_path):
    settings = _settings(tmp_path)
    _prepare_database(settings)
    acp, store = GatedAcp(), FakeObjectStore()
    execution = ChatExecution(settings)

    def factory(connection):
        return ChatService(
            connection, acp=acp, settings=settings,
            library=LibraryService(connection, store, settings),
        )

    session_id, turn_id, body = await reserve(settings, acp)
    execution.start(turn_id, factory, _principal(), session_id, body)
    seen = []
    async with aclosing(execution.events(_principal(), turn_id, 0)) as stream:
        async for frame in stream:
            event = decode(frame)
            seen.append(event)
            if event[1] == "message_delta":
                break
    assert turn_id in execution.tasks
    assert not acp.closed.is_set()

    async with aclosing(execution.events(_principal(), turn_id, None)) as stream:
        seq, name, snapshot = decode(await anext(stream))
    assert name == "turn_snapshot"
    assert snapshot["status"] == "running"
    assert snapshot["responseText"].startswith("Progress before disconnect.")
    acp.release.set()
    resumed = [decode(frame) async for frame in execution.events(_principal(), turn_id, seq)]
    ids = [event[0] for event in resumed]
    assert ids == sorted(set(ids))
    reconstructed = snapshot["responseText"] + "".join(
        event[2]["delta"] for event in resumed if event[1] == "message_delta"
    )
    assert reconstructed.endswith("Final answer after reconnect.")
    assert resumed[-1][1:] == ("turn_state", resumed[-1][2])
    assert resumed[-1][2]["status"] == "completed"
    assert resumed[-1][2]["eventSeq"] == resumed[-1][0]
    assert acp.calls == 1
    replay = [decode(frame) async for frame in execution.events(_principal(), turn_id, 0)]
    assert replay[-1][2]["responseText"] == reconstructed.strip()
    assert (await execution.cancel(_principal(), turn_id))["status"] == "completed"
    assert acp.calls == 1

    # An explicit cancellation closes actual upstream consumption and preserves partial text.
    acp.release.clear()
    acp.closed.clear()
    session_id, cancelled_id, body = await reserve(settings, acp)
    execution.start(cancelled_id, factory, _principal(), session_id, body)
    async with aclosing(execution.events(_principal(), cancelled_id, 0)) as stream:
        async for frame in stream:
            if decode(frame)[1] == "message_delta":
                break
    assert (await execution.cancel(_principal(), cancelled_id))["status"] == "cancelled"
    await asyncio.wait_for(acp.closed.wait(), 1)
    with open_database_connection(settings) as connection:
        cancelled = ChatRepository(connection).get_turn(cancelled_id)
        assert cancelled.responseText.startswith("Progress before disconnect.")
        assert cancelled.completedAt

    # A killed worker's persisted progress becomes an explicit interrupted failure on startup.
    _, orphan_id, _ = await reserve(settings, acp)
    with open_database_connection(settings) as connection:
        ChatRepository(connection).append_event(orphan_id, "message_delta", {"delta": "saved"})
        connection.commit()
    execution.recover()
    with open_database_connection(settings) as connection:
        orphan = ChatRepository(connection).get_turn(orphan_id)
        assert (orphan.status, orphan.stopReason, orphan.responseText) == (
            "failed", "interrupted", "saved"
        )
    await execution.close()


def test_capability_echo_is_redacted_across_every_chunk_boundary():
    token = "lturn_turn_" + "a" * 32 + "." + "b" * 64
    for split in range(1, len(token)):
        redactor = _CredentialRedactor(token)
        output = redactor.push("before " + token[:split])
        output += redactor.push(token[split:] + " after") + redactor.finish()
        assert output == "before [redacted] after"


@pytest.mark.asyncio
async def test_legacy_progress_is_private_on_all_local_history_paths(tmp_path):
    settings = _settings(tmp_path)
    _prepare_database(settings)
    session_id, turn_id, _ = await reserve(settings, GatedAcp())
    private = "[tool] Tool: personal_library/find_personal_file\nbwrap: uid map denied"
    with open_database_connection(settings) as connection:
        service = ChatService(connection, settings=settings)
        service._finalize(turn_id, ["Business answer"], "end_turn", None,
                          reasoning_parts=[private])
        service.repo.append_event(turn_id, "reasoning_delta", {"delta": private})
        connection.commit()
        messages = await service.list_messages(_principal(), session_id)
        assert messages[0]["reasoningText"] == "Processing your request.\n"
        transcript = service._local_transcript(session_id)
        assert private not in str(transcript)
        assert transcript[-1]["text"] == "Business answer"
    execution = ChatExecution(settings)
    for after in (None, 0):
        frames = [decode(frame) async for frame in execution.events(_principal(), turn_id, after)]
        assert frames
        assert "personal_library" not in str(frames)
        assert "bwrap" not in str(frames)

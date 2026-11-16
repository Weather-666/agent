from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.clients.acp_gateway import AcpGatewayClient
from app.db import open_database_connection
from app.domain.chat import ChatTurnRequest, CreateSessionRequest
from app.services.chat_service import ChatService
from test_expert_runtime import _create_expert, _prepare_database, _principal, _settings


@pytest.fixture
def chat_context(tmp_path: Path):
    settings = _settings(tmp_path).model_copy(update={"default_tenant_id": "shared_default"})
    _prepare_database(settings)
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
        connection.execute("update experts set status = 'published' where id = ?", (expert.id,))
        connection.execute(
            """insert into users (id, email, password_hash, name, status)
            values ('member_two', 'two@example.com', 'hash', 'Two', 'active')"""
        )
        connection.commit()
        chat = ChatService(connection, settings=settings, acp=AcpGatewayClient(settings))
        yield chat, expert, settings


@pytest.mark.asyncio
async def test_team_members_use_distinct_workspaces(chat_context) -> None:
    chat, expert, _settings = chat_context
    workspaces = []
    for principal in (_principal(), _principal().model_copy(update={"user_id": "member_two"})):
        session = await chat.create_session(principal, CreateSessionRequest(expertId=expert.id))
        row = chat._require_session(principal, session.id)
        assert json.loads(row["agent_options"])["workspaceScope"] == "user"
        workspaces.append(Path(chat._prepare_acp_cwd(row)))
    assert workspaces[0] != workspaces[1]
    (workspaces[0] / "personal-report.txt").write_text("MEMBER_ONE_PRIVATE")
    assert not (workspaces[1] / "personal-report.txt").exists()


@pytest.mark.asyncio
async def test_legacy_team_session_isolates_without_copying_files_or_resuming_old_ids(
    chat_context,
) -> None:
    chat, expert, settings = chat_context
    principal = _principal()
    session = await chat.create_session(principal, CreateSessionRequest(expertId=expert.id))
    chat.connection.execute(
        """update chat_sessions set agent_options = ?, acp_session_id = 'old-private',
        acp_search_session_id = 'old-search-private' where id = ?""",
        ('{\n  "otherOption":"preserved"\n}', session.id),
    )
    chat.connection.commit()
    legacy = chat._require_session(principal, session.id)
    stale = dict(legacy)
    shared = Path(settings.acp_cwd_base) / str(principal.active_tenant_id)
    (shared / "legacy-private.txt").write_text("UNASSIGNED_PRIVATE_DATA")

    workspace = Path(chat._prepare_acp_cwd(legacy))

    assert legacy["acp_session_id"] is None
    assert legacy["acp_search_session_id"] is None
    assert chat._acp_route(legacy, False).session_id is None
    assert chat._acp_route(legacy, True).session_id is None
    assert json.loads(legacy["agent_options"]) == {
        "workspaceScope": "user", "otherOption": "preserved"
    }
    assert (shared / "legacy-private.txt").read_text() == "UNASSIGNED_PRIVATE_DATA"
    assert not (workspace / "legacy-private.txt").exists()

    chat.repo.set_acp_session_id(session.id, "new-isolated-session", "2026-09-08T00:00:00Z")
    chat.connection.commit()
    chat._prepare_acp_cwd(stale)
    assert stale["acp_session_id"] == "new-isolated-session"


@pytest.mark.asyncio
async def test_legacy_shared_transcript_uses_owned_history_without_resuming_agent(
    chat_context,
) -> None:
    chat, expert, _settings = chat_context
    principal = _principal()
    session = await chat.create_session(principal, CreateSessionRequest(expertId=expert.id))
    turn_id = chat.reserve_turn(principal, session.id, ChatTurnRequest(question="My old question"))
    chat.connection.execute(
        "update chat_turns set status = 'completed', response_text = 'My old answer' where id = ?",
        (turn_id,),
    )
    chat.connection.execute(
        "update chat_sessions set agent_options = '{}', acp_session_id = 'shared-old' where id = ?",
        (session.id,),
    )
    chat.connection.commit()

    transcript = await chat.get_transcript(principal, session.id)

    assert transcript["source"] == "local"
    assert transcript["messages"] == [
        {"role": "user", "text": "My old question"},
        {"role": "assistant", "text": "My old answer"},
    ]
    assert chat._require_session(principal, session.id)["acp_session_id"] == "shared-old"


def test_unbound_legacy_session_keeps_default_workspace(chat_context) -> None:
    chat, _expert, _settings = chat_context
    row = {"expert_id": None, "agent_options": "{}"}
    assert chat._prepare_acp_cwd(row) == chat.acp.prepare_default_cwd()

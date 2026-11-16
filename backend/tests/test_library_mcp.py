import json

import pytest
from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import open_database_connection
from app.services.chat_repository import ChatRepository
from app.services.library_mcp_service import library_mcp_authorization, library_turn_capability
from test_expert_runtime import _create_expert, _prepare_database
from test_library_team import _app, _personal_headers, _settings, _upload
from test_app import FakeObjectStore


@pytest.mark.parametrize("bound", [False, True])
def test_personal_file_tools_require_current_capability_and_preserve_provenance(tmp_path, bound):
    settings = _settings(tmp_path)
    _prepare_database(settings)
    store = FakeObjectStore()
    with open_database_connection(settings) as connection:
        expert = _create_expert(connection)
    runtime_identity = {"expert_id": expert.id, "runtime_type": "codex"} if bound else None
    runtime_id = expert.id if bound else "default"
    with TestClient(_app(settings, store)) as client:
        headers = _personal_headers(client, settings, "alice", "alice@example.com")
        other = _personal_headers(client, settings, "bob", "bob@example.com")
        owned, _ = _upload(client, store, headers, name="purchase.md", content=b"ALICE_ONLY")
        foreign, _ = _upload(client, store, other, name="purchase.md", content=b"BOB_SECRET")
        _upload(client, store, headers, name="purchase-extra.md", content=b"OTHER_CANDIDATE")
        session_id, turn_id = "session_" + uuid4().hex, "turn_" + uuid4().hex
        with open_database_connection(settings) as connection:
            repo = ChatRepository(connection)
            repo.create_session(
                session_id=session_id, tenant_id="tenant_default", user_id="alice",
                title="Library test", agent_options={}, now="2026-09-10T00:00:00+00:00",
                runtime_identity=runtime_identity,
            )
            repo.create_turn(
                turn_id=turn_id, session_id=session_id, tenant_id="tenant_default",
                user_id="alice", request_text="Read purchase.md", model=None,
                query_rewrite=False, multi_hop_config=None, token_usage_scope="",
                runtime_identity=runtime_identity,
                now="2026-09-10T00:00:00+00:00",
            )
            row = repo.get_session_row("tenant_default", "alice", session_id)
            capability = library_turn_capability(settings, row, turn_id)
            connection.commit()
        url = f"/internal/mcp/library/{runtime_id}"
        auth = {"Authorization": library_mcp_authorization(settings, runtime_id)}

        def call(name, **arguments):
            response = client.post(url, headers=auth, json={
                "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            })
            assert response.status_code == 200
            return response.json()["result"]

        assert client.post(url, json={"method": "tools/list"}).status_code == 401
        denied = call("find_personal_file", fileName="purchase.md")
        assert denied["isError"]
        denied = call(
            "find_personal_file", fileName="purchase.md",
            turnCapability=capability, userId="bob", turnId=turn_id,
        )
        assert denied["structuredContent"]["code"] == "LIBRARY_TOOL_ARGUMENT_INVALID"
        denied = call(
            "find_personal_file", fileName="purchase.md",
            turnCapability=capability[:-1] + ("c" if capability[-1] != "c" else "d"),
        )
        assert denied["structuredContent"]["code"] == "LIBRARY_TURN_FORBIDDEN"
        wrong_runtime = "default" if bound else expert.id
        cross_runtime = client.post(
            f"/internal/mcp/library/{wrong_runtime}",
            headers={"Authorization": library_mcp_authorization(settings, wrong_runtime)},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "find_personal_file",
                             "arguments": {"fileName": "purchase.md", "turnCapability": capability}}},
        ).json()["result"]
        assert cross_runtime["structuredContent"]["code"] == "LIBRARY_TURN_FORBIDDEN"
        read = call("find_personal_file", fileName="purchase.md", turnCapability=capability)
        assert read["structuredContent"]["content"] == "ALICE_ONLY"
        assert read["structuredContent"]["complete"] is True
        assert "BOB_SECRET" not in json.dumps(read)
        denied = call("read_personal_file", fileId=foreign["id"], turnCapability=capability)
        assert denied["structuredContent"]["code"] == "LIBRARY_FILE_NOT_FOUND"
        candidates = call("find_personal_file", fileName="purchase", turnCapability=capability)
        assert candidates["structuredContent"]["status"] == "needs_clarification"
        assert len(candidates["structuredContent"]["candidates"]) == 2
        missing = call("find_personal_file", fileName="absent.md", turnCapability=capability)
        assert missing["structuredContent"]["code"] == "LIBRARY_FILE_NOT_FOUND"

        with open_database_connection(settings) as connection:
            turn = ChatRepository(connection).get_turn(turn_id)
            assert [item["fileId"] for item in turn.attachments] == [owned["id"]]
            audit = connection.execute(
                "select metadata from audit_events where action = 'library.agent_content_read'"
            ).fetchone()
            assert json.loads(audit["metadata"])["turnId"] == turn_id
            assert capability not in json.dumps(turn.model_dump())
            connection.execute("update chat_turns set status = 'completed' where id = ?", (turn_id,))
            connection.commit()
        expired = call("find_personal_file", fileName="purchase.md", turnCapability=capability)
        assert expired["structuredContent"]["code"] == "LIBRARY_TURN_FORBIDDEN"

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.chat_service import ChatService
from app.services.knowledge_mcp_service import (
    KnowledgeMcpService,
    knowledge_mcp_authorization,
)


def test_knowledge_mcp_requires_expert_capability_and_lists_one_read_only_tool(tmp_path) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'knowledge-mcp.sqlite3'}",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    app = create_app(settings)
    expert_id = "0123456789abcdef"
    url = f"/internal/mcp/knowledge/{expert_id}"

    with TestClient(app) as client:
        unauthorized = client.post(
            url,
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
        )
        assert unauthorized.status_code == 401

        listed = client.post(
            url,
            headers={"Authorization": knowledge_mcp_authorization(settings, expert_id)},
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )

    assert listed.status_code == 200
    tools = listed.json()["result"]["tools"]
    assert [tool["name"] for tool in tools] == ["search_expert_knowledge"]
    assert tools[0]["inputSchema"]["required"] == ["query", "turnId"]


@pytest.mark.asyncio
async def test_knowledge_mcp_search_persists_tool_selected_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = [{"citationId": "cite_1"}]
    stored: list[list[dict]] = []
    commits: list[bool] = []
    connection = SimpleNamespace(commit=lambda: commits.append(True))
    service = KnowledgeMcpService(connection, Settings(_env_file=None))
    service.repo = SimpleNamespace(
        get_turn=lambda _turn_id: SimpleNamespace(
            status="running",
            expertId="0123456789abcdef",
            retrievalRefs=existing,
        ),
        update_turn_retrieval_refs=lambda _turn_id, refs: stored.append(refs),
    )

    async def retrieve(
        _self,
        expert_id: str,
        query: str,
        turn_id: str,
        *,
        citation_offset: int,
    ) -> tuple[str, list[dict], bool]:
        assert (expert_id, query, turn_id, citation_offset) == (
            "0123456789abcdef",
            "refund policy",
            "turn_1",
            1,
        )
        return "[cite_2] evidence", [{"citationId": "cite_2"}], True

    monkeypatch.setattr(ChatService, "retrieve_expert_knowledge", retrieve)

    context, refs, scoped = await service.search(
        "0123456789abcdef",
        "turn_1",
        "refund policy",
    )

    assert context == "[cite_2] evidence"
    assert refs == [{"citationId": "cite_2"}]
    assert scoped is True
    assert stored == [[*existing, {"citationId": "cite_2"}]]
    assert commits == [True]


def test_knowledge_mcp_keeps_cited_evidence_visible_to_runtime(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'knowledge-mcp-evidence.sqlite3'}",
        jwt_secret="test-secret-with-at-least-32-bytes",
    )
    expert_id = "0123456789abcdef"
    evidence = "[cite_1] Receiving code ORIOLE-TEST; quarantine damaged cartons for 37 hours."

    async def search(_self, selected_expert_id, turn_id, query):
        assert (selected_expert_id, turn_id, query) == (
            expert_id,
            "turn_1",
            "Oriole receiving policy",
        )
        return evidence, [{"citationId": "cite_1"}], True

    monkeypatch.setattr(KnowledgeMcpService, "search", search)

    with TestClient(create_app(settings)) as client:
        response = client.post(
            f"/internal/mcp/knowledge/{expert_id}",
            headers={"Authorization": knowledge_mcp_authorization(settings, expert_id)},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "search_expert_knowledge",
                    "arguments": {"turnId": "turn_1", "query": "Oriole receiving policy"},
                },
            },
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] is False
    assert result["content"] == [{"type": "text", "text": evidence}]
    # Codex uses structuredContent instead of content when both are present.
    model_visible = result.get("structuredContent", result["content"])
    assert evidence in str(model_visible)

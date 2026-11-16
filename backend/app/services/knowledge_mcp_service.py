from __future__ import annotations

import hashlib
import hmac

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.services.chat_repository import ChatRepository
from app.services.chat_service import ChatService


KNOWLEDGE_MCP_SERVER_NAME = "expert_knowledge"
KNOWLEDGE_MCP_TOOL_NAME = "search_expert_knowledge"
KNOWLEDGE_MCP_AUTHORIZATION_SECRET_REF = "EXPERT_KNOWLEDGE_AUTHORIZATION"


def knowledge_mcp_authorization(settings: Settings, expert_id: str) -> str:
    signature = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        f"knowledge-mcp:{expert_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return f"Bearer kmcp_{signature}"


class KnowledgeMcpService:
    def __init__(self, connection: DatabaseConnection, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings
        self.repo = ChatRepository(connection)

    async def search(self, expert_id: str, turn_id: str, query: str) -> tuple[str, list[dict], bool]:
        turn = self.repo.get_turn(turn_id)
        if turn is None or turn.status != "running" or turn.expertId != expert_id:
            raise ApiError(
                409,
                "KNOWLEDGE_MCP_TURN_INVALID",
                "Knowledge search is not valid for this Chat Turn",
            )

        existing_refs = turn.retrievalRefs
        context, refs, knowledge_scoped = await ChatService(
            self.connection,
            settings=self.settings,
        ).retrieve_expert_knowledge(
            expert_id,
            query,
            turn_id,
            citation_offset=len(existing_refs),
        )
        if refs:
            self.repo.update_turn_retrieval_refs(turn_id, [*existing_refs, *refs])
            self.connection.commit()
        return context, refs, knowledge_scoped

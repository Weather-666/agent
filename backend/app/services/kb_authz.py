from __future__ import annotations

from typing import Literal

from app.core.errors import ApiError
from app.domain.auth import Principal
from app.domain.knowledge import KnowledgeBase


KbAction = Literal["read", "update", "delete", "doc", "build", "archive", "activate"]

# Actions that require an active knowledge base. `activate` is deliberately absent because it
# un-archives the base. `delete` is also absent because retiring an archived base is a valid
# lifecycle operation; the route-level `kb:delete` permission still controls who may do it.
# `archive` remains present so re-archiving returns the same 409 as other active-only actions.
_ACTIVE_ONLY_ACTIONS = {"update", "doc", "build", "archive"}


def authorize_kb_access(principal: Principal, kb: KnowledgeBase, action: KbAction) -> None:
    """Lifecycle gate on top of the action-level platform permission.

    Knowledge bases are platform-owned: who may act is decided entirely by the platform
    permission on the route (require_platform_permission). Ownership and visibility are NOT
    access-control inputs -- owner_user_id is only creator attribution. The single remaining
    resource rule is the lifecycle one: an archived knowledge base rejects active-only actions.

    This is NOT tenant isolation -- tenant principals cannot reach these routes at all.
    """
    if action in _ACTIVE_ONLY_ACTIONS and kb.status != "active":
        raise ApiError(409, "KB_ARCHIVED", "Knowledge base is archived")

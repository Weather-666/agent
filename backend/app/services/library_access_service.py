from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.auth import Principal
from app.services._sql import fetch_all, fetch_one, json_load


PERSONAL_LIBRARY_QUOTA_BYTES = 2 * 1024**3
TEAM_LIBRARY_QUOTA_BYTES = 20 * 1024**3


class LibraryAction(StrEnum):
    LIST = "list"
    READ = "read"
    UPLOAD = "upload"
    RENAME = "rename"
    DELETE = "delete"
    PROMOTE = "promote"
    USE_AGENT = "useAgent"


@dataclass(frozen=True)
class LibrarySpaceAccess:
    space_type: str
    status: str
    quota_bytes: int
    user_id: str
    tenant_id: str | None
    role: str | None
    capabilities: dict[str, bool]


class LibraryAccessService:
    """Single request-time authorization source for personal and team Library operations."""

    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def space_access(
        self,
        principal: Principal,
        space_type: str,
        *,
        uploaded_by_user_id: str | None = None,
        allow_unavailable: bool = False,
    ) -> LibrarySpaceAccess:
        if principal.active_tenant_id is None:
            raise ApiError(401, "AUTH_UNAUTHORIZED", "Missing active tenant")
        user = self._active_user(principal.user_id)
        if user is None:
            raise ApiError(401, "AUTH_USER_DISABLED", "User not found or disabled")
        tenant_id = str(principal.active_tenant_id)

        if space_type == "personal":
            quota = self._personal_quota(tenant_id)
            return LibrarySpaceAccess(
                space_type="personal",
                status="full",
                quota_bytes=quota,
                user_id=principal.user_id,
                tenant_id=None,
                role=None,
                capabilities=_capabilities(
                    space_type="personal",
                    status="full",
                    role=None,
                    user_id=principal.user_id,
                    uploaded_by_user_id=uploaded_by_user_id,
                ),
            )
        if space_type != "team":
            raise ApiError(400, "LIBRARY_SPACE_INVALID", "spaceType must be personal or team")

        member = self._active_team_member(tenant_id, principal.user_id)
        state, quota = self._team_state(tenant_id)
        role = str(member["role"]) if member is not None else None
        access = LibrarySpaceAccess(
            space_type="team",
            status=state,
            quota_bytes=quota,
            user_id=principal.user_id,
            tenant_id=tenant_id,
            role=role,
            capabilities=_capabilities(
                space_type="team",
                status=state,
                role=role,
                user_id=principal.user_id,
                uploaded_by_user_id=uploaded_by_user_id,
            ),
        )
        if not allow_unavailable and (member is None or state == "none"):
            raise ApiError(403, "TEAM_LIBRARY_FORBIDDEN", "Team Library is not available")
        return access

    @staticmethod
    def capabilities_for(
        access: LibrarySpaceAccess, *, uploaded_by_user_id: str | None = None
    ) -> dict[str, bool]:
        """Derive per-file capabilities from one request-time space access result."""
        return _capabilities(
            space_type=access.space_type,
            status=access.status,
            role=access.role,
            user_id=access.user_id,
            uploaded_by_user_id=uploaded_by_user_id,
        )

    def require(
        self,
        principal: Principal,
        space_type: str,
        action: LibraryAction,
        *,
        uploaded_by_user_id: str | None = None,
        hide_missing: bool = False,
    ) -> LibrarySpaceAccess:
        access = self.space_access(
            principal,
            space_type,
            uploaded_by_user_id=uploaded_by_user_id,
            allow_unavailable=hide_missing,
        )
        if not access.capabilities.get(action.value, False):
            if hide_missing:
                raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
            code = (
                "TEAM_LIBRARY_READ_ONLY"
                if space_type == "team" and access.status == "read_only"
                else "LIBRARY_ACTION_FORBIDDEN"
            )
            raise ApiError(403, code, f"Library action is not allowed: {action.value}")
        return access

    def _active_user(self, user_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            "select id from users where id = ? and status = 'active' limit 1",
            (user_id,),
        )

    def _active_team_member(self, tenant_id: str, user_id: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select tm.role
            from tenant_members tm
            inner join tenants t on t.id = tm.tenant_id
            inner join users u on u.id = tm.user_id
            where tm.tenant_id = ? and tm.user_id = ?
              and t.type = 'team' and t.status = 'active' and u.status = 'active'
            limit 1
            """,
            (tenant_id, user_id),
        )

    def _personal_quota(self, tenant_id: str) -> int:
        current = self._current_entitlements(tenant_id)
        if current is None:
            return PERSONAL_LIBRARY_QUOTA_BYTES
        value = current.get("personalLibraryQuotaBytes")
        return max(int(value if value is not None else PERSONAL_LIBRARY_QUOTA_BYTES), 0)

    def _team_state(self, tenant_id: str) -> tuple[str, int]:
        current = self._current_entitlements(tenant_id)
        if current is not None and bool(current.get("teamLibraryEnabled", False)):
            value = current.get("teamLibraryQuotaBytes")
            quota = value if value is not None else TEAM_LIBRARY_QUOTA_BYTES
            return "full", max(int(quota), 0)
        historical = fetch_one(
            self.connection,
            """
            select max_quota_bytes
            from team_library_entitlement_history
            where tenant_id = ?
            limit 1
            """,
            (tenant_id,),
        )
        if historical is None:
            return "none", 0
        return "read_only", max(int(historical["max_quota_bytes"]), 0)

    def _current_entitlements(self, tenant_id: str) -> dict[str, Any] | None:
        rows = fetch_all(
            self.connection,
            """
            select s.status, s.current_period_end, s.current_period_start, s.created_at,
                   p.entitlements
            from subscriptions s
            inner join plans p on p.id = s.plan_id
            where s.tenant_id = ?
            order by s.current_period_start desc, s.created_at desc, s.id desc
            """,
            (tenant_id,),
        )
        now = datetime.now(timezone.utc)
        for row in rows:
            if _subscription_usable(row, now):
                return json_load(row.get("entitlements"))
        return None


def _subscription_usable(row: dict[str, Any], now: datetime) -> bool:
    if str(row.get("status")) not in {"active", "trialing", "past_due"}:
        return False
    value = row.get("current_period_end")
    if value is None:
        return True
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed > now


def _capabilities(
    *,
    space_type: str,
    status: str,
    role: str | None,
    user_id: str,
    uploaded_by_user_id: str | None,
) -> dict[str, bool]:
    if space_type == "personal":
        return {action.value: True for action in LibraryAction}
    is_member = role is not None
    is_admin = role == "admin"
    is_uploader = uploaded_by_user_id is not None and uploaded_by_user_id == user_id
    return {
        LibraryAction.LIST.value: is_member and status in {"full", "read_only"},
        LibraryAction.READ.value: is_member and status in {"full", "read_only"},
        LibraryAction.UPLOAD.value: is_member and status == "full",
        LibraryAction.RENAME.value: is_member and status == "full" and (is_admin or is_uploader),
        LibraryAction.DELETE.value: is_member
        and (
            (status == "full" and (is_admin or is_uploader)) or (status == "read_only" and is_admin)
        ),
        LibraryAction.PROMOTE.value: False,
        LibraryAction.USE_AGENT.value: is_member and status == "full",
    }

from __future__ import annotations

from uuid import uuid4

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.auth import TenantRole
from app.services._sql import execute, fetch_one


class DefaultTenantService:
    """Attach tenant-less active users to the configured shared fallback tenant."""

    def __init__(self, connection: DatabaseConnection, settings: Settings) -> None:
        self.connection = connection
        self.settings = settings

    def ensure_membership(self, user_id: str) -> str:
        tenant_id = self.settings.default_tenant_id.strip()
        tenant = fetch_one(
            self.connection,
            "select id, status from tenants where id = ? limit 1",
            (tenant_id,),
        )
        if tenant is None or tenant["status"] != "active":
            raise ApiError(
                503,
                "DEFAULT_TENANT_UNAVAILABLE",
                "Default tenant is not available",
            )

        execute(
            self.connection,
            """
            insert into tenant_members (id, tenant_id, user_id, role)
            values (?, ?, ?, ?)
            on conflict (tenant_id, user_id) do nothing
            """,
            (
                f"member_{uuid4().hex}",
                tenant_id,
                user_id,
                TenantRole.MEMBER.value,
            ),
        )
        return tenant_id

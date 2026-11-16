from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

from app.db import DatabaseConnection
from app.services._sql import execute, fetch_one, rowcount


@dataclass(frozen=True)
class ProfileRecord:
    id: str
    email: str
    name: str
    preferred_locale: str | None
    avatar_object_key: str | None
    updated_at: Any


class ProfileRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def begin_write(self) -> None:
        if isinstance(self.connection, sqlite3.Connection):
            self.connection.execute("begin immediate")

    def get(self, user_id: str, *, for_update: bool = False) -> ProfileRecord | None:
        suffix = ""
        if for_update and not isinstance(self.connection, sqlite3.Connection):
            suffix = " for update"
        row = fetch_one(
            self.connection,
            """
            select id, email, name, preferred_locale, avatar_object_key, updated_at
            from users
            where id = ?
            """
            + suffix,
            (user_id,),
        )
        if not row:
            return None
        return ProfileRecord(
            id=str(row["id"]),
            email=str(row["email"]),
            name=str(row["name"]),
            preferred_locale=(
                str(row["preferred_locale"])
                if row["preferred_locale"] is not None
                else None
            ),
            avatar_object_key=(
                str(row["avatar_object_key"])
                if row["avatar_object_key"] is not None
                else None
            ),
            updated_at=row["updated_at"],
        )

    def update_profile(
        self,
        user_id: str,
        *,
        update_name: bool,
        name: str | None,
        update_preferred_locale: bool,
        preferred_locale: str | None,
    ) -> bool:
        assignments: list[str] = []
        params: list[object] = []
        if update_name:
            assignments.append("name = ?")
            params.append(name)
        if update_preferred_locale:
            assignments.append("preferred_locale = ?")
            params.append(preferred_locale)
        if not assignments:
            return True
        assignments.append("updated_at = CURRENT_TIMESTAMP")
        params.append(user_id)
        cursor = execute(
            self.connection,
            f"update users set {', '.join(assignments)} where id = ?",
            params,
        )
        return rowcount(cursor) == 1

    def update_avatar_object_key(self, user_id: str, object_key: str | None) -> bool:
        cursor = execute(
            self.connection,
            """
            update users
            set avatar_object_key = ?, updated_at = CURRENT_TIMESTAMP
            where id = ?
            """,
            (object_key, user_id),
        )
        return rowcount(cursor) == 1

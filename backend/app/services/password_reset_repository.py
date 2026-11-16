from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from app.db import DatabaseConnection
from app.services._sql import execute, fetch_one, rowcount


@dataclass(frozen=True)
class PasswordResetUser:
    id: str
    email: str
    status: str


@dataclass(frozen=True)
class PasswordResetCode:
    id: str
    user_id: str
    code_hash: str
    expires_at: str
    attempt_count: int
    used_at: str | None
    created_at: str


class PasswordResetRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def begin_write(self) -> None:
        if isinstance(self.connection, sqlite3.Connection):
            self.connection.execute("begin immediate")

    def find_user_by_email_for_update(self, email: str) -> PasswordResetUser | None:
        suffix = "" if isinstance(self.connection, sqlite3.Connection) else " for update"
        row = fetch_one(
            self.connection,
            "select id, email, status from users where email = ? limit 1" + suffix,
            (email,),
        )
        if not row:
            return None
        return PasswordResetUser(
            id=str(row["id"]),
            email=str(row["email"]),
            status=str(row["status"]),
        )

    def latest_available_code(self, user_id: str, *, for_update: bool) -> PasswordResetCode | None:
        suffix = (
            ""
            if isinstance(self.connection, sqlite3.Connection) or not for_update
            else " for update"
        )
        row = fetch_one(
            self.connection,
            """
            select id, user_id, code_hash, expires_at, attempt_count, used_at, created_at
            from password_reset_codes
            where user_id = ? and used_at is null
            order by created_at desc
            limit 1
            """
            + suffix,
            (user_id,),
        )
        if not row:
            return None
        return PasswordResetCode(
            id=str(row["id"]),
            user_id=str(row["user_id"]),
            code_hash=str(row["code_hash"]),
            expires_at=str(row["expires_at"]),
            attempt_count=int(row["attempt_count"]),
            used_at=str(row["used_at"]) if row["used_at"] is not None else None,
            created_at=str(row["created_at"]),
        )

    def invalidate_available_codes(self, user_id: str, used_at: str) -> None:
        execute(
            self.connection,
            """
            update password_reset_codes
            set used_at = ?
            where user_id = ? and used_at is null
            """,
            (used_at, user_id),
        )

    def create_code(
        self,
        *,
        code_id: str,
        user_id: str,
        code_hash: str,
        expires_at: str,
        created_at: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into password_reset_codes
              (id, user_id, code_hash, expires_at, attempt_count, created_at)
            values (?, ?, ?, ?, 0, ?)
            """,
            (code_id, user_id, code_hash, expires_at, created_at),
        )

    def invalidate_code(self, code_id: str, used_at: str) -> None:
        execute(
            self.connection,
            """
            update password_reset_codes
            set used_at = ?
            where id = ? and used_at is null
            """,
            (used_at, code_id),
        )

    def record_failed_attempt(self, code_id: str, *, attempted_at: str, maximum: int) -> None:
        execute(
            self.connection,
            """
            update password_reset_codes
            set attempt_count = attempt_count + 1,
                used_at = case
                  when attempt_count + 1 >= ? then ?
                  else used_at
                end
            where id = ? and used_at is null
            """,
            (maximum, attempted_at, code_id),
        )

    def occupy_code(
        self,
        code_id: str,
        *,
        used_at: str,
        maximum: int,
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            update password_reset_codes
            set used_at = ?
            where id = ?
              and used_at is null
              and expires_at > ?
              and attempt_count < ?
            """,
            (used_at, code_id, used_at, maximum),
        )
        return rowcount(cursor) == 1

    def update_password(self, user_id: str, password_hash: str, updated_at: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update users
            set password_hash = ?, updated_at = ?
            where id = ? and status = 'active'
            """,
            (password_hash, updated_at, user_id),
        )
        return rowcount(cursor) == 1

    def revoke_refresh_tokens(self, user_id: str, revoked_at: str) -> None:
        execute(
            self.connection,
            """
            update refresh_tokens
            set revoked_at = ?
            where user_id = ? and revoked_at is null
            """,
            (revoked_at, user_id),
        )

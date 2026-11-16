from __future__ import annotations

from typing import Any

from app.db import DatabaseConnection
from app.domain.library import LibraryFileRecord, LibrarySort, LibraryUploadSessionRecord
from app.services._sql import execute, fetch_all, fetch_one, json_param, rowcount


_COLUMNS = (
    "id, space_type, owner_user_id, owner_tenant_id, uploaded_by_user_id, display_name, "
    "normalized_name, mime_type, file_type, extension, size_bytes, storage_object_key, "
    "lifecycle, expires_at, chat_session_id, created_at, updated_at"
)

_SESSION_COLUMNS = (
    "id, file_id, tenant_id, space_type, owner_user_id, owner_tenant_id, uploaded_by_user_id, "
    "requested_name, mime_type, file_type, extension, file_size_bytes, storage_bucket, "
    "storage_object_key, status, expires_at, reserved_bytes"
)


_SORT_SQL: dict[str, str] = {
    "updatedAt_desc": "updated_at desc, id asc",
    "updatedAt_asc": "updated_at asc, id asc",
    "name_asc": "lower(display_name) asc, id asc",
    "name_desc": "lower(display_name) desc, id asc",
    "size_desc": "size_bytes desc, id asc",
    "size_asc": "size_bytes asc, id asc",
}


class LibraryRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    def create_file(
        self,
        *,
        file_id: str,
        user_id: str | None,
        tenant_id: str,
        space_type: str,
        owner_user_id: str | None,
        owner_tenant_id: str | None,
        uploaded_by_user_id: str | None,
        original_name: str,
        safe_name: str,
        display_name: str,
        normalized_name: str,
        mime_type: str | None,
        file_type: str,
        extension: str | None,
        size_bytes: int,
        storage_bucket: str,
        storage_object_key: str,
        content_hash: str | None,
        preview_supported: bool,
        metadata: dict[str, Any],
        now: str,
        source: str = "library",
        lifecycle: str = "permanent",
        expires_at: str | None = None,
        promoted_at: str | None = None,
        chat_session_id: str | None = None,
    ) -> LibraryFileRecord:
        execute(
            self.connection,
            """
            insert into library_files (
              id, user_id, tenant_id, space_type, owner_user_id, owner_tenant_id,
              uploaded_by_user_id, original_name, safe_name, display_name, normalized_name,
              mime_type, file_type, extension, size_bytes, storage_bucket, storage_object_key, content_hash,
              preview_supported, metadata, source, lifecycle, expires_at, promoted_at,
              chat_session_id, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                file_id,
                user_id,
                tenant_id,
                space_type,
                owner_user_id,
                owner_tenant_id,
                uploaded_by_user_id,
                original_name,
                safe_name,
                display_name,
                normalized_name,
                mime_type,
                file_type,
                extension,
                size_bytes,
                storage_bucket,
                storage_object_key,
                content_hash,
                preview_supported,
                json_param(self.connection, metadata),
                source,
                lifecycle,
                expires_at,
                promoted_at,
                chat_session_id,
                now,
                now,
            ),
        )
        file = self.get_file_by_id(file_id)
        assert file is not None
        return file

    def create_upload_session(
        self,
        *,
        session_id: str,
        file_id: str,
        user_id: str,
        tenant_id: str,
        space_type: str,
        owner_user_id: str | None,
        owner_tenant_id: str | None,
        uploaded_by_user_id: str,
        original_name: str,
        safe_name: str,
        requested_name: str,
        mime_type: str | None,
        file_type: str,
        extension: str | None,
        file_size_bytes: int,
        storage_bucket: str,
        storage_object_key: str,
        content_hash: str | None,
        reserved_bytes: int,
        expires_at: str,
        now: str,
        chat_session_id: str | None = None,
    ) -> None:
        execute(
            self.connection,
            """
            insert into library_upload_sessions (
              id, file_id, user_id, tenant_id, space_type, owner_user_id, owner_tenant_id,
              uploaded_by_user_id, original_name, safe_name, requested_name, mime_type, file_type,
              extension, file_size_bytes, storage_bucket, storage_object_key, content_hash,
              reserved_bytes, status, expires_at, chat_session_id, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'initiated', ?, ?, ?, ?)
            """,
            (
                session_id,
                file_id,
                user_id,
                tenant_id,
                space_type,
                owner_user_id,
                owner_tenant_id,
                uploaded_by_user_id,
                original_name,
                safe_name,
                requested_name,
                mime_type,
                file_type,
                extension,
                file_size_bytes,
                storage_bucket,
                storage_object_key,
                content_hash,
                reserved_bytes,
                expires_at,
                chat_session_id,
                now,
                now,
            ),
        )

    def get_upload_session(self, session_id: str) -> LibraryUploadSessionRecord | None:
        row = fetch_one(
            self.connection,
            f"select {_SESSION_COLUMNS} from library_upload_sessions where id = ? limit 1",
            (session_id,),
        )
        return _map_session(row)

    def set_upload_session_status(
        self,
        session_id: str,
        status: str,
        now: str,
        *,
        completed: bool = False,
    ) -> None:
        completed_at = now if completed else None
        execute(
            self.connection,
            """
            update library_upload_sessions
            set status = ?, completed_at = coalesce(?, completed_at), updated_at = ?
            where id = ?
            """,
            (status, completed_at, now, session_id),
        )

    def list_expired_upload_sessions(self, before: str) -> list[LibraryUploadSessionRecord]:
        rows = fetch_all(
            self.connection,
            f"""
            select {_SESSION_COLUMNS} from library_upload_sessions
            where status in ('initiated', 'failed') and expires_at < ?
            """,
            (before,),
        )
        return [s for s in (_map_session(row) for row in rows) if s is not None]

    def get_file(self, user_id: str, tenant_id: str, file_id: str) -> LibraryFileRecord | None:
        del tenant_id
        row = fetch_one(
            self.connection,
            f"""
            select {_COLUMNS} from library_files
            where id = ? and space_type = 'personal' and owner_user_id = ? and deleted_at is null
            limit 1
            """,
            (file_id, user_id),
        )
        return _map_file(row)

    def get_file_by_id(
        self, file_id: str, *, include_deleted: bool = False
    ) -> LibraryFileRecord | None:
        deleted_filter = "" if include_deleted else "and deleted_at is null"
        row = fetch_one(
            self.connection,
            f"select {_COLUMNS} from library_files where id = ? {deleted_filter} limit 1",
            (file_id,),
        )
        return _map_file(row)

    def list_files(
        self,
        *,
        space_type: str,
        owner_key: str,
        keyword: str | None,
        file_type: str | None,
        sort: LibrarySort,
        limit: int,
        offset: int,
        lifecycle: str = "permanent",
        chat_session_id: str | None = None,
        now: str | None = None,
    ) -> tuple[list[LibraryFileRecord], int]:
        owner_column = "owner_user_id" if space_type == "personal" else "owner_tenant_id"
        where = ["space_type = ?", f"{owner_column} = ?", "deleted_at is null"]
        params: list[Any] = [space_type, owner_key]
        if lifecycle == "temporary":
            # Temporary listing (§11): owner-scoped and never expired. Without a session it returns
            # all of the caller's temporary files (bound and unbound); with one, only that session's
            # bound files. Both stay owner-scoped, so there is no cross-user exposure.
            where.append("lifecycle = 'temporary'")
            where.append("expires_at > ?")
            params.append(now)
            if chat_session_id is not None:
                where.append("chat_session_id = ?")
                params.append(chat_session_id)
        else:
            # §11 safeguard: the default listing is permanent-only, unconditionally. A caller that
            # does not explicitly ask for temporary files never sees them.
            where.append("lifecycle = 'permanent'")
        if file_type is not None:
            where.append("file_type = ?")
            params.append(file_type)
        if keyword:
            where.append("lower(display_name) like ?")
            params.append(f"%{keyword.lower()}%")
        where_sql = " and ".join(where)
        total_row = fetch_one(
            self.connection,
            f"select count(*) as count from library_files where {where_sql}",
            params,
        )
        rows = fetch_all(
            self.connection,
            f"""
            select {_COLUMNS} from library_files
            where {where_sql}
            order by {_SORT_SQL[sort]}
            limit ? offset ?
            """,
            [*params, limit, offset],
        )
        return [f for f in (_map_file(row) for row in rows) if f is not None], int(
            total_row["count"] if total_row else 0
        )

    def promote_file(
        self, user_id: str, tenant_id: str, file_id: str, now: str
    ) -> LibraryFileRecord | None:
        """Flip a live temporary file to permanent with no byte copy (§10).

        The expiry guard lives in the SQL where clause so a promotion racing the GC pass cannot
        resurrect an already-expired file. Returns None if nothing matched (expired, already
        permanent, or deleted).
        """
        cursor = execute(
            self.connection,
            """
            update library_files
            set lifecycle = 'permanent', expires_at = null, promoted_at = ?, updated_at = ?
            where id = ? and owner_user_id = ? and space_type = 'personal'
              and deleted_at is null
              and lifecycle = 'temporary'
              and expires_at > ?
            """,
            (now, now, file_id, user_id, now),
        )
        if rowcount(cursor) == 0:
            return None
        return self.get_file(user_id, tenant_id, file_id)

    def bind_temporary_file_session(
        self, user_id: str, tenant_id: str, file_id: str, session_id: str, now: str
    ) -> LibraryFileRecord | None:
        """Bind an unbound temporary file to a session, exactly once (§7 auto-bind).

        The `chat_session_id is null` guard makes the bind idempotent and race-safe: a second
        attempt (or a concurrent turn in another session) matches no row. Returns None when nothing
        was bound; the caller re-reads to see who won.
        """
        cursor = execute(
            self.connection,
            """
            update library_files
            set chat_session_id = ?, updated_at = ?
            where id = ? and owner_user_id = ? and space_type = 'personal'
              and deleted_at is null
              and lifecycle = 'temporary'
              and chat_session_id is null
              and expires_at > ?
            """,
            (session_id, now, file_id, user_id, now),
        )
        if rowcount(cursor) == 0:
            return None
        return self.get_file(user_id, tenant_id, file_id)

    def list_expired_temporary_files(self, now: str, limit: int = 100) -> list[tuple[str, str]]:
        """Temporary files past their deadline (§12.2). Returns (file_id, storage_object_key)."""
        rows = fetch_all(
            self.connection,
            """
            select id, storage_object_key from library_files
            where lifecycle = 'temporary' and deleted_at is null and expires_at < ?
            order by expires_at asc
            limit ?
            """,
            (now, limit),
        )
        return [(str(row["id"]), str(row["storage_object_key"])) for row in rows]

    def soft_delete_file(self, file_id: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update library_files
            set deleted_at = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (now, now, file_id),
        )
        return rowcount(cursor) > 0

    def list_deleted(self, limit: int) -> list[tuple[str, str]]:
        rows = fetch_all(
            self.connection,
            """
            select id, storage_object_key from library_files
            where deleted_at is not null
            order by deleted_at asc
            limit ?
            """,
            (limit,),
        )
        return [(str(row["id"]), str(row["storage_object_key"])) for row in rows]

    def hard_delete_file(self, file_id: str) -> None:
        execute(self.connection, "delete from library_files where id = ?", (file_id,))

    def ensure_usage(
        self,
        *,
        space_type: str,
        owner_key: str,
        owner_user_id: str | None,
        owner_tenant_id: str | None,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into library_space_usage (
              space_type, owner_key, owner_user_id, owner_tenant_id, created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?)
            on conflict (space_type, owner_key) do nothing
            """,
            (space_type, owner_key, owner_user_id, owner_tenant_id, now, now),
        )

    def reserve_bytes(
        self, *, space_type: str, owner_key: str, amount: int, quota: int, now: str
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            update library_space_usage
            set reserved_bytes = reserved_bytes + ?, updated_at = ?
            where space_type = ? and owner_key = ?
              and used_bytes + reserved_bytes + ? <= ?
            """,
            (amount, now, space_type, owner_key, amount, quota),
        )
        return rowcount(cursor) > 0

    def release_reserved_bytes(
        self, *, space_type: str, owner_key: str, amount: int, now: str
    ) -> None:
        execute(
            self.connection,
            """
            update library_space_usage
            set reserved_bytes = case when reserved_bytes >= ? then reserved_bytes - ? else 0 end,
                updated_at = ?
            where space_type = ? and owner_key = ?
            """,
            (amount, amount, now, space_type, owner_key),
        )

    def complete_reserved_bytes(
        self, *, space_type: str, owner_key: str, amount: int, now: str
    ) -> bool:
        cursor = execute(
            self.connection,
            """
            update library_space_usage
            set reserved_bytes = reserved_bytes - ?, used_bytes = used_bytes + ?,
                updated_at = ?
            where space_type = ? and owner_key = ? and reserved_bytes >= ?
            """,
            (amount, amount, now, space_type, owner_key, amount),
        )
        return rowcount(cursor) > 0

    def release_used_bytes(self, *, space_type: str, owner_key: str, amount: int, now: str) -> None:
        execute(
            self.connection,
            """
            update library_space_usage
            set used_bytes = case when used_bytes >= ? then used_bytes - ? else 0 end,
                updated_at = ?
            where space_type = ? and owner_key = ?
            """,
            (amount, amount, now, space_type, owner_key),
        )

    def get_usage(self, space_type: str, owner_key: str) -> dict[str, int]:
        row = fetch_one(
            self.connection,
            """
            select used_bytes, reserved_bytes from library_space_usage
            where space_type = ? and owner_key = ?
            """,
            (space_type, owner_key),
        )
        return {
            "usedBytes": int(row["used_bytes"]) if row else 0,
            "reservedBytes": int(row["reserved_bytes"]) if row else 0,
        }

    def usage_breakdown(self, space_type: str, owner_key: str) -> dict:
        # Expired temporary files still consume quota until GC soft-deletes them.
        owner_column = "owner_user_id" if space_type == "personal" else "owner_tenant_id"
        rows = fetch_all(
            self.connection,
            f"""
            select lifecycle, file_type, count(*) as count, coalesce(sum(size_bytes), 0) as bytes
            from library_files
            where space_type = ? and {owner_column} = ? and deleted_at is null
            group by lifecycle, file_type
            """,
            (space_type, owner_key),
        )
        result = {
            lifecycle: {"fileCount": 0, "fileBytes": 0, "imageCount": 0, "imageBytes": 0}
            for lifecycle in ("permanent", "temporary")
        }
        for row in rows:
            category = result[str(row["lifecycle"])]
            kind = str(row["file_type"])
            category[f"{kind}Count"] = int(row["count"])
            category[f"{kind}Bytes"] = int(row["bytes"])
        return result

    def list_display_names(self, space_type: str, owner_key: str) -> list[str]:
        owner_column = "owner_user_id" if space_type == "personal" else "owner_tenant_id"
        lifecycle_filter = "and lifecycle = 'permanent'" if space_type == "personal" else ""
        rows = fetch_all(
            self.connection,
            f"""
            select display_name from library_files
            where space_type = ? and {owner_column} = ? and deleted_at is null {lifecycle_filter}
            """,
            (space_type, owner_key),
        )
        return [str(row["display_name"]) for row in rows]

    def claim_name(
        self, *, space_type: str, owner_key: str, normalized_name: str, file_id: str, now: str
    ) -> None:
        execute(
            self.connection,
            """
            insert into library_name_claims (space_type, owner_key, normalized_name, file_id, created_at)
            values (?, ?, ?, ?, ?)
            """,
            (space_type, owner_key, normalized_name, file_id, now),
        )

    def release_name_claim(self, file_id: str) -> None:
        execute(self.connection, "delete from library_name_claims where file_id = ?", (file_id,))

    def update_file_name(
        self, file_id: str, *, display_name: str, normalized_name: str, safe_name: str, now: str
    ) -> None:
        execute(
            self.connection,
            """
            update library_files
            set original_name = ?, display_name = ?, normalized_name = ?, safe_name = ?, updated_at = ?
            where id = ? and deleted_at is null
            """,
            (display_name, display_name, normalized_name, safe_name, now, file_id),
        )

    def create_delivery_capability(
        self,
        *,
        token: str,
        file_id: str,
        actor_user_id: str,
        tenant_id: str,
        turn_id: str,
        max_uses: int,
        expires_at: str,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into library_delivery_capabilities (
              token, file_id, actor_user_id, tenant_id, turn_id, max_uses, expires_at, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (token, file_id, actor_user_id, tenant_id, turn_id, max_uses, expires_at, now),
        )

    def get_delivery_capability(self, token: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select token, file_id, actor_user_id, tenant_id, turn_id, use_count, max_uses, expires_at
            from library_delivery_capabilities where token = ? limit 1
            """,
            (token,),
        )

    def consume_delivery_capability(self, token: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update library_delivery_capabilities
            set use_count = use_count + 1
            where token = ? and expires_at > ? and use_count < max_uses
            """,
            (token, now),
        )
        return rowcount(cursor) > 0

    def usage_reconciliation_rows(self, now: str) -> list[dict[str, Any]]:
        ledger = fetch_all(
            self.connection,
            """
            select space_type, owner_key, used_bytes, reserved_bytes
            from library_space_usage order by space_type, owner_key
            """,
        )
        actual_files = fetch_all(
            self.connection,
            """
            select space_type,
                   case when space_type = 'personal' then owner_user_id else owner_tenant_id end as owner_key,
                   coalesce(sum(size_bytes), 0) as used_bytes
            from library_files
            where deleted_at is null
            group by space_type,
                     case when space_type = 'personal' then owner_user_id else owner_tenant_id end
            """,
        )
        actual_sessions = fetch_all(
            self.connection,
            """
            select space_type,
                   case when space_type = 'personal' then owner_user_id else owner_tenant_id end as owner_key,
                   coalesce(sum(reserved_bytes), 0) as reserved_bytes
            from library_upload_sessions
            where status = 'initiated'
            group by space_type,
                     case when space_type = 'personal' then owner_user_id else owner_tenant_id end
            """,
        )
        by_key: dict[tuple[str, str], dict[str, Any]] = {}
        for row in ledger:
            key = (str(row["space_type"]), str(row["owner_key"]))
            by_key[key] = {
                "spaceType": key[0],
                "ownerKey": key[1],
                "ledgerUsedBytes": int(row["used_bytes"]),
                "ledgerReservedBytes": int(row["reserved_bytes"]),
                "actualUsedBytes": 0,
                "actualReservedBytes": 0,
            }
        for field, rows in (
            ("actualUsedBytes", actual_files),
            ("actualReservedBytes", actual_sessions),
        ):
            source = "used_bytes" if field == "actualUsedBytes" else "reserved_bytes"
            for row in rows:
                if row.get("owner_key") is None:
                    continue
                key = (str(row["space_type"]), str(row["owner_key"]))
                item = by_key.setdefault(
                    key,
                    {
                        "spaceType": key[0],
                        "ownerKey": key[1],
                        "ledgerUsedBytes": 0,
                        "ledgerReservedBytes": 0,
                        "actualUsedBytes": 0,
                        "actualReservedBytes": 0,
                    },
                )
                item[field] = int(row[source])
        return list(by_key.values())


def _map_file(row: dict[str, Any] | None) -> LibraryFileRecord | None:
    if not row:
        return None
    return LibraryFileRecord(
        id=str(row["id"]),
        spaceType=str(row.get("space_type") or "personal"),
        ownerUserId=(str(row["owner_user_id"]) if row.get("owner_user_id") is not None else None),
        ownerTenantId=(
            str(row["owner_tenant_id"]) if row.get("owner_tenant_id") is not None else None
        ),
        uploadedByUserId=(
            str(row["uploaded_by_user_id"]) if row.get("uploaded_by_user_id") is not None else None
        ),
        displayName=str(row["display_name"]),
        normalizedName=str(row["normalized_name"]),
        mimeType=str(row["mime_type"]) if row.get("mime_type") is not None else None,
        fileType=str(row["file_type"]),
        extension=str(row["extension"]) if row.get("extension") is not None else None,
        sizeBytes=int(row["size_bytes"]),
        storageObjectKey=str(row["storage_object_key"]),
        lifecycle=str(row["lifecycle"]) if row.get("lifecycle") is not None else "permanent",
        expiresAt=str(row["expires_at"]) if row.get("expires_at") is not None else None,
        chatSessionId=str(row["chat_session_id"])
        if row.get("chat_session_id") is not None
        else None,
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )


def _map_session(row: dict[str, Any] | None) -> LibraryUploadSessionRecord | None:
    if not row:
        return None
    return LibraryUploadSessionRecord(
        id=str(row["id"]),
        fileId=str(row["file_id"]),
        tenantId=str(row["tenant_id"]),
        spaceType=str(row.get("space_type") or "personal"),
        ownerUserId=(str(row["owner_user_id"]) if row.get("owner_user_id") is not None else None),
        ownerTenantId=(
            str(row["owner_tenant_id"]) if row.get("owner_tenant_id") is not None else None
        ),
        uploadedByUserId=(
            str(row["uploaded_by_user_id"]) if row.get("uploaded_by_user_id") is not None else None
        ),
        requestedName=str(row["requested_name"]),
        mimeType=str(row["mime_type"]) if row.get("mime_type") is not None else None,
        fileType=str(row["file_type"]),
        extension=str(row["extension"]) if row.get("extension") is not None else None,
        fileSizeBytes=int(row["file_size_bytes"]),
        storageBucket=str(row["storage_bucket"]),
        storageObjectKey=str(row["storage_object_key"]),
        reservedBytes=int(row.get("reserved_bytes") or 0),
        status=str(row["status"]),
        expiresAt=str(row["expires_at"]),
    )

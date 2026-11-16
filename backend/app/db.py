from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.core.config import Settings

SqliteConnection = sqlite3.Connection
DatabaseConnection = SqliteConnection | Any


def migrate_database(settings: Settings) -> None:
    schema_dir = Path(settings.database_schema_dir)
    files = sorted(schema_dir.glob("*.sql"))
    if not files:
        raise RuntimeError(f"No SQL schema files found under {schema_dir}")

    if _is_sqlite_url(settings.database_url):
        with open_database_connection(settings) as connection:
            _migrate_sqlite(connection, files)
        return

    if _is_postgres_url(settings.database_url):
        _migrate_postgres(settings.database_url, files)
        return

    raise RuntimeError(f"Unsupported database URL: {settings.database_url}")


@contextmanager
def open_database_connection(settings: Settings) -> Iterator[DatabaseConnection]:
    if _is_sqlite_url(settings.database_url):
        connection = _open_sqlite(settings.database_url)
        try:
            yield connection
        finally:
            connection.close()
        return

    if _is_postgres_url(settings.database_url):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError as exc:  # pragma: no cover - exercised only without optional dependency
            raise RuntimeError("PostgreSQL requires the psycopg dependency.") from exc

        with psycopg.connect(settings.database_url, row_factory=dict_row) as connection:
            yield connection
        return

    raise RuntimeError(f"Unsupported database URL: {settings.database_url}")


def _migrate_sqlite(connection: SqliteConnection, files: list[Path]) -> None:
    connection.execute("pragma foreign_keys = on")
    _rebuild_legacy_library_tables(connection)
    _rebuild_legacy_audit_events(connection)
    for file in files:
        sql = _sqlite_compatible_sql(file.read_text(encoding="utf-8"))
        for statement in _split_sql_statements(sql):
            _execute_sqlite_statement(connection, statement)
    connection.commit()


def _rebuild_legacy_audit_events(connection: SqliteConnection) -> None:
    """Expand the SQLite operation-type check while preserving append-only audit rows."""
    row = connection.execute(
        "select sql from sqlite_master where type = 'table' and name = 'audit_events'"
    ).fetchone()
    if row is None or "'read'" in str(row[0]).lower():
        return

    connection.commit()
    connection.execute("pragma foreign_keys = off")
    try:
        connection.execute("begin immediate")
        connection.execute("alter table audit_events rename to audit_events_legacy")
        connection.execute(
            """
            create table audit_events (
              id text primary key,
              request_id text not null,
              occurred_at text not null,
              category text not null,
              action text not null,
              operation_type text not null check (
                operation_type in (
                  'create', 'read', 'update', 'delete', 'login', 'grant', 'revoke', 'upload'
                )
              ),
              actor_user_id text not null,
              actor_name text not null,
              actor_email text not null,
              actor_platform_roles text not null default '[]',
              tenant_id text,
              tenant_name text,
              resource_type text not null,
              resource_id text not null,
              resource_name text,
              changes text not null default '{}',
              metadata text not null default '{}',
              client_ip text
            )
            """
        )
        connection.execute(
            """
            insert into audit_events (
              id, request_id, occurred_at, category, action, operation_type,
              actor_user_id, actor_name, actor_email, actor_platform_roles,
              tenant_id, tenant_name, resource_type, resource_id, resource_name,
              changes, metadata, client_ip
            )
            select
              id, request_id, occurred_at, category, action, operation_type,
              actor_user_id, actor_name, actor_email, actor_platform_roles,
              tenant_id, tenant_name, resource_type, resource_id, resource_name,
              changes, metadata, client_ip
            from audit_events_legacy
            """
        )
        connection.execute("drop table audit_events_legacy")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("pragma foreign_keys = on")


def _rebuild_legacy_library_tables(connection: SqliteConnection) -> None:
    """One-time idempotent rebuild for Library uploader FKs that SQLite cannot alter in place."""
    file_columns = _sqlite_table_columns(connection, "library_files")
    if not file_columns or int(file_columns.get("user_id", {}).get("notnull", 0)) == 0:
        return

    session_columns = _sqlite_table_columns(connection, "library_upload_sessions")
    connection.commit()
    connection.execute("pragma foreign_keys = off")
    try:
        connection.execute("begin immediate")
        connection.execute("alter table library_files rename to library_files_legacy")
        connection.execute(
            """
            create table library_files (
              id text primary key,
              user_id text references users(id) on delete set null,
              tenant_id text not null references tenants(id) on delete cascade,
              space_type text not null default 'personal' check (space_type in ('personal', 'team')),
              owner_user_id text references users(id) on delete cascade,
              owner_tenant_id text references tenants(id) on delete cascade,
              uploaded_by_user_id text references users(id) on delete set null,
              original_name text not null,
              safe_name text not null,
              display_name text not null,
              normalized_name text not null,
              mime_type text,
              file_type text not null check (file_type in ('image', 'file')),
              extension text,
              size_bytes integer not null,
              storage_bucket text not null,
              storage_object_key text not null unique,
              content_hash text,
              preview_supported integer not null default 0,
              metadata text not null default '{}',
              created_at text not null default CURRENT_TIMESTAMP,
              updated_at text not null default CURRENT_TIMESTAMP,
              deleted_at text,
              source text not null default 'library' check (source in ('library', 'chat_upload')),
              lifecycle text not null default 'permanent' check (lifecycle in ('temporary', 'permanent')),
              expires_at text,
              promoted_at text,
              chat_session_id text references chat_sessions(id) on delete set null,
              constraint library_files_lifecycle_invariant check (
                (lifecycle = 'temporary' and expires_at is not null)
                or (lifecycle = 'permanent' and expires_at is null)
              ),
              constraint library_files_owner_invariant check (
                (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null)
                or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null)
              )
            )
            """
        )
        file_select = {
            "space_type": "'personal'",
            "owner_user_id": "user_id",
            "owner_tenant_id": "null",
            "uploaded_by_user_id": "user_id",
            "display_name": "original_name",
            "normalized_name": "lower(original_name)",
            "source": "'library'",
            "lifecycle": "'permanent'",
            "expires_at": "null",
            "promoted_at": "null",
            "chat_session_id": "null",
        }
        file_order = [
            "id",
            "user_id",
            "tenant_id",
            "space_type",
            "owner_user_id",
            "owner_tenant_id",
            "uploaded_by_user_id",
            "original_name",
            "safe_name",
            "display_name",
            "normalized_name",
            "mime_type",
            "file_type",
            "extension",
            "size_bytes",
            "storage_bucket",
            "storage_object_key",
            "content_hash",
            "preview_supported",
            "metadata",
            "created_at",
            "updated_at",
            "deleted_at",
            "source",
            "lifecycle",
            "expires_at",
            "promoted_at",
            "chat_session_id",
        ]
        expressions = [name if name in file_columns else file_select[name] for name in file_order]
        connection.execute(
            f"insert into library_files ({', '.join(file_order)}) "
            f"select {', '.join(expressions)} from library_files_legacy"
        )
        connection.execute("drop table library_files_legacy")

        if session_columns:
            connection.execute(
                "alter table library_upload_sessions rename to library_upload_sessions_legacy"
            )
            connection.execute(
                """
                create table library_upload_sessions (
                  id text primary key,
                  file_id text not null,
                  user_id text references users(id) on delete set null,
                  tenant_id text not null references tenants(id) on delete cascade,
                  space_type text not null default 'personal' check (space_type in ('personal', 'team')),
                  owner_user_id text references users(id) on delete cascade,
                  owner_tenant_id text references tenants(id) on delete cascade,
                  uploaded_by_user_id text references users(id) on delete set null,
                  original_name text not null,
                  safe_name text not null,
                  requested_name text not null,
                  mime_type text,
                  file_type text not null check (file_type in ('image', 'file')),
                  extension text,
                  file_size_bytes integer not null,
                  storage_bucket text not null,
                  storage_object_key text not null unique,
                  content_hash text,
                  reserved_bytes integer not null,
                  status text not null default 'initiated' check (status in ('initiated', 'completed', 'expired', 'failed')),
                  expires_at text not null,
                  completed_at text,
                  created_at text not null default CURRENT_TIMESTAMP,
                  updated_at text not null default CURRENT_TIMESTAMP,
                  chat_session_id text references chat_sessions(id) on delete cascade,
                  constraint library_upload_sessions_owner_invariant check (
                    (space_type = 'personal' and owner_user_id is not null and owner_tenant_id is null)
                    or (space_type = 'team' and owner_user_id is null and owner_tenant_id is not null)
                  )
                )
                """
            )
            session_select = {
                "space_type": "'personal'",
                "owner_user_id": "user_id",
                "owner_tenant_id": "null",
                "uploaded_by_user_id": "user_id",
                "requested_name": "original_name",
                "reserved_bytes": (
                    "case when status = 'initiated' and expires_at > CURRENT_TIMESTAMP "
                    "then file_size_bytes else 0 end"
                ),
                "chat_session_id": "null",
            }
            session_order = [
                "id",
                "file_id",
                "user_id",
                "tenant_id",
                "space_type",
                "owner_user_id",
                "owner_tenant_id",
                "uploaded_by_user_id",
                "original_name",
                "safe_name",
                "requested_name",
                "mime_type",
                "file_type",
                "extension",
                "file_size_bytes",
                "storage_bucket",
                "storage_object_key",
                "content_hash",
                "reserved_bytes",
                "status",
                "expires_at",
                "completed_at",
                "created_at",
                "updated_at",
                "chat_session_id",
            ]
            session_expressions = [
                name if name in session_columns else session_select[name] for name in session_order
            ]
            connection.execute(
                f"insert into library_upload_sessions ({', '.join(session_order)}) "
                f"select {', '.join(session_expressions)} from library_upload_sessions_legacy"
            )
            connection.execute("drop table library_upload_sessions_legacy")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("pragma foreign_keys = on")


def _sqlite_table_columns(connection: SqliteConnection, table: str) -> dict[str, dict[str, Any]]:
    return {
        str(row[1]): {"type": row[2], "notnull": row[3], "default": row[4], "pk": row[5]}
        for row in connection.execute(f"pragma table_info({table})").fetchall()
    }


def _migrate_postgres(database_url: str, files: list[Path]) -> None:
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError as exc:  # pragma: no cover - exercised only without optional dependency
        raise RuntimeError("PostgreSQL requires the psycopg dependency.") from exc

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        with connection.cursor() as cursor:
            for file in files:
                cursor.execute(file.read_text(encoding="utf-8"))
        connection.commit()


def _execute_sqlite_statement(connection: SqliteConnection, statement: str) -> None:
    statement = _strip_sql_comments(statement)
    if not statement:
        return
    normalized = " ".join(statement.lower().split())

    add_column = re.match(
        r"alter\s+table\s+(\w+)\s+add\s+column\s+if\s+not\s+exists\s+(\w+)\s+(.+)",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if add_column:
        table, column, definition = add_column.groups()
        if _sqlite_column_exists(connection, table, column):
            return
        connection.execute(f"alter table {table} add column {column} {definition}")
        return

    drop_column = re.match(
        r"alter\s+table\s+(\w+)\s+drop\s+column\s+if\s+exists\s+(\w+)",
        statement,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if drop_column:
        table, column = drop_column.groups()
        if _sqlite_column_exists(connection, table, column):
            connection.execute(f"alter table {table} drop column {column}")
        return

    if (
        " alter column " in f" {normalized} "
        or " add constraint " in f" {normalized} "
        or " drop constraint " in f" {normalized} "
    ):
        return

    connection.execute(statement)


def _sqlite_column_exists(connection: SqliteConnection, table: str, column: str) -> bool:
    rows = connection.execute(f"pragma table_info({table})").fetchall()
    return any(row[1] == column for row in rows)


def _sqlite_compatible_sql(sql: str) -> str:
    sql = re.sub(r"do\s+\$\$.*?\$\$;", "", sql, flags=re.IGNORECASE | re.DOTALL)
    replacements = [
        (r"'(\{\}|\[\])'::jsonb", r"'\1'"),
        (r"::jsonb", ""),
        (r"\btimestamptz\b", "text"),
        (r"\bjsonb\b", "text"),
        (r"\bbigint\b", "integer"),
        (r"\bboolean\b", "integer"),
        (r"default\s+now\(\)", "default CURRENT_TIMESTAMP"),
        (r"default\s+false\b", "default 0"),
        (r"default\s+true\b", "default 1"),
    ]
    for pattern, replacement in replacements:
        sql = re.sub(pattern, replacement, sql, flags=re.IGNORECASE)
    # PostgreSQL merges JSON objects with `left || right`. SQLite's `||` concatenates text, while
    # JSON1 provides the equivalent left-to-right object merge as json_patch(left, right).
    sql = re.sub(
        r"('(?:[^']|'')*')\s*\|\|\s*entitlements",
        r"json_patch(\1, entitlements)",
        sql,
        flags=re.IGNORECASE,
    )
    return sql


def _strip_sql_comments(statement: str) -> str:
    lines = []
    for line in statement.splitlines():
        stripped = line.strip()
        if stripped.startswith("--"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def _split_sql_statements(sql: str) -> list[str]:
    statements = []
    current: list[str] = []
    in_single_quote = False
    index = 0

    while index < len(sql):
        char = sql[index]
        current.append(char)
        if char == "'" and sql[index - 1 : index] != "\\":
            in_single_quote = not in_single_quote
        if char == ";" and not in_single_quote:
            statement = "".join(current).strip().rstrip(";").strip()
            if statement:
                statements.append(statement)
            current = []
        index += 1

    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


def _open_sqlite(database_url: str) -> SqliteConnection:
    path = _sqlite_path(database_url)
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    # Foreign keys are off by default per SQLite connection. Enable them so runtime FK behavior
    # (e.g. ON DELETE CASCADE) matches PostgreSQL, where constraints are always enforced.
    connection.execute("pragma foreign_keys = on")
    return connection


def _sqlite_path(database_url: str) -> str:
    if database_url == "sqlite:///:memory:":
        return ":memory:"
    if database_url.startswith("sqlite:///"):
        return database_url.removeprefix("sqlite:///")
    raise RuntimeError(f"Unsupported sqlite URL: {database_url}")


def _is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite:///")


def _is_postgres_url(database_url: str) -> bool:
    return database_url.startswith(("postgres://", "postgresql://"))

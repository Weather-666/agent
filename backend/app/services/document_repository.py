from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.db import DatabaseConnection
from app.domain.knowledge import Document
from app.services._sql import execute, fetch_all, fetch_one, json_load, json_param, rowcount


@dataclass
class UploadSession:
    id: str
    knowledge_base_id: str
    document_id: str
    replaces_document_id: str | None
    actor_user_id: str
    file_name: str
    file_type: str
    content_type: str | None
    file_size_bytes: int
    object_bucket: str
    object_key: str
    status: str
    expires_at: str


_DOC_COLUMNS = (
    "id, knowledge_base_id, file_name, file_type, mime_type, storage_key, object_bucket, "
    "object_version, content_hash, source_sha256, indexed_sha256, file_size_bytes, "
    "parse_status, index_status, lightrag_track_id, index_document_id, "
    "index_pipeline_version, "
    "markdown_storage_key, markdown_sha256, parse_error, last_error, metadata, "
    "created_at, updated_at"
)

_SESSION_COLUMNS = (
    "id, knowledge_base_id, document_id, replaces_document_id, actor_user_id, file_name, "
    "file_type, content_type, file_size_bytes, object_bucket, object_key, status, expires_at"
)


class DocumentRepository:
    def __init__(self, connection: DatabaseConnection) -> None:
        self.connection = connection

    # document_upload_sessions ----------------------------------------------------

    def create_session(
        self,
        *,
        session_id: str,
        knowledge_base_id: str,
        document_id: str,
        replaces_document_id: str | None,
        actor_user_id: str,
        file_name: str,
        file_type: str,
        content_type: str | None,
        file_size_bytes: int,
        object_bucket: str,
        object_key: str,
        expires_at: str,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into document_upload_sessions (
              id, knowledge_base_id, document_id, replaces_document_id, actor_user_id,
              upload_mode, file_name,
              file_type, content_type, file_size_bytes, object_bucket, object_key, status,
              expires_at, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, 'single_put', ?, ?, ?, ?, ?, ?, 'initiated', ?, ?, ?)
            """,
            (
                session_id,
                knowledge_base_id,
                document_id,
                replaces_document_id,
                actor_user_id,
                file_name,
                file_type,
                content_type,
                file_size_bytes,
                object_bucket,
                object_key,
                expires_at,
                now,
                now,
            ),
        )

    def get_session(self, session_id: str) -> UploadSession | None:
        row = fetch_one(
            self.connection,
            f"select {_SESSION_COLUMNS} from document_upload_sessions where id = ? limit 1",
            (session_id,),
        )
        return _map_session(row)

    def set_session_status(self, session_id: str, status: str, now: str) -> None:
        completed = now if status == "completed" else None
        execute(
            self.connection,
            """
            update document_upload_sessions
            set status = ?, completed_at = ?, updated_at = ?
            where id = ?
            """,
            (status, completed, now, session_id),
        )

    def complete_session_if_initiated(self, session_id: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update document_upload_sessions
            set status = 'completed', completed_at = ?, updated_at = ?
            where id = ? and status = 'initiated'
            """,
            (now, now, session_id),
        )
        return rowcount(cursor) > 0

    def list_expired_sessions(self, before: str) -> list[UploadSession]:
        rows = fetch_all(
            self.connection,
            f"""
            select {_SESSION_COLUMNS} from document_upload_sessions
            where status = 'initiated' and expires_at < ?
            """,
            (before,),
        )
        return [s for s in (_map_session(row) for row in rows) if s is not None]

    # documents ------------------------------------------------------------------

    def create_document(
        self,
        *,
        document_id: str,
        knowledge_base_id: str,
        file_name: str,
        file_type: str,
        mime_type: str | None,
        storage_key: str,
        object_bucket: str,
        content_hash: str | None,
        file_size_bytes: int,
        created_by: str,
        now: str,
    ) -> Document:
        execute(
            self.connection,
            """
            insert into documents (
              id, knowledge_base_id, file_name, file_type, mime_type, storage_key, object_bucket,
              object_version, content_hash, source_sha256, file_size_bytes,
              parse_status, index_status,
              created_by, metadata, created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'pending', ?, ?, ?, ?)
            """,
            (
                document_id,
                knowledge_base_id,
                file_name,
                file_type,
                mime_type,
                storage_key,
                object_bucket,
                None,  # object_version
                content_hash,
                content_hash,
                file_size_bytes,
                created_by,
                json_param(self.connection, {}),
                now,
                now,
            ),
        )
        self._record_source_version(
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            source_sha256=content_hash,
            file_name=file_name,
            file_type=file_type,
            mime_type=mime_type,
            storage_key=storage_key,
            object_bucket=object_bucket,
            file_size_bytes=file_size_bytes,
            now=now,
        )
        document = self.get_document(knowledge_base_id, document_id)
        assert document is not None  # just inserted
        return document

    def replace_document_source(
        self,
        *,
        document_id: str,
        knowledge_base_id: str,
        file_name: str,
        file_type: str,
        mime_type: str | None,
        storage_key: str,
        object_bucket: str,
        source_sha256: str,
        file_size_bytes: int,
        now: str,
    ) -> Document:
        self._record_source_version(
            document_id=document_id,
            knowledge_base_id=knowledge_base_id,
            source_sha256=source_sha256,
            file_name=file_name,
            file_type=file_type,
            mime_type=mime_type,
            storage_key=storage_key,
            object_bucket=object_bucket,
            file_size_bytes=file_size_bytes,
            now=now,
        )
        execute(
            self.connection,
            """
            update documents
            set file_name = ?, file_type = ?, mime_type = ?, storage_key = ?,
                object_bucket = ?, content_hash = ?, source_sha256 = ?,
                file_size_bytes = ?,
                parse_status = case when source_sha256 = ? then parse_status else 'pending' end,
                index_status = case when source_sha256 = ? then index_status else 'stale' end,
                parse_error = case when source_sha256 = ? then parse_error else null end,
                last_error = case when source_sha256 = ? then last_error else null end,
                markdown_storage_key = case
                  when source_sha256 = ? then markdown_storage_key else null end,
                markdown_sha256 = case
                  when source_sha256 = ? then markdown_sha256 else null end,
                lightrag_track_id = case
                  when source_sha256 = ? then lightrag_track_id else null end,
                updated_at = ?
            where id = ? and knowledge_base_id = ? and deleted_at is null
            """,
            (
                file_name,
                file_type,
                mime_type,
                storage_key,
                object_bucket,
                source_sha256,
                source_sha256,
                file_size_bytes,
                source_sha256,
                source_sha256,
                source_sha256,
                source_sha256,
                source_sha256,
                source_sha256,
                source_sha256,
                now,
                document_id,
                knowledge_base_id,
            ),
        )
        document = self.get_document(knowledge_base_id, document_id)
        assert document is not None  # updated above
        return document

    def get_source_version(self, document_id: str, source_sha256: str) -> dict[str, Any] | None:
        return fetch_one(
            self.connection,
            """
            select * from knowledge_document_source_versions
            where document_id = ? and source_sha256 = ?
            limit 1
            """,
            (document_id, source_sha256),
        )

    def _record_source_version(
        self,
        *,
        document_id: str,
        knowledge_base_id: str,
        source_sha256: str,
        file_name: str,
        file_type: str,
        mime_type: str | None,
        storage_key: str,
        object_bucket: str,
        file_size_bytes: int,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into knowledge_document_source_versions (
              document_id, source_sha256, knowledge_base_id, file_name, file_type, mime_type,
              storage_key, object_bucket, file_size_bytes, created_at
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict (document_id, source_sha256) do nothing
            """,
            (
                document_id,
                source_sha256,
                knowledge_base_id,
                file_name,
                file_type,
                mime_type,
                storage_key,
                object_bucket,
                file_size_bytes,
                now,
            ),
        )

    def get_document(self, knowledge_base_id: str, document_id: str) -> Document | None:
        row = fetch_one(
            self.connection,
            f"""
            select {_DOC_COLUMNS} from documents
            where id = ? and knowledge_base_id = ? and deleted_at is null
            limit 1
            """,
            (document_id, knowledge_base_id),
        )
        return _map_document(row)

    def list_documents(self, knowledge_base_id: str) -> list[Document]:
        rows = fetch_all(
            self.connection,
            f"""
            select {_DOC_COLUMNS} from documents
            where knowledge_base_id = ? and deleted_at is null
            order by created_at desc, id asc
            """,
            (knowledge_base_id,),
        )
        return [d for d in (_map_document(row) for row in rows) if d is not None]

    def find_live_document_by_source_sha(
        self,
        knowledge_base_id: str,
        source_sha256: str,
        *,
        exclude_document_id: str | None = None,
    ) -> Document | None:
        exclude_clause = ""
        params: tuple[Any, ...] = (knowledge_base_id, source_sha256)
        if exclude_document_id is not None:
            exclude_clause = "and id <> ?"
            params = (*params, exclude_document_id)
        row = fetch_one(
            self.connection,
            f"""
            select {_DOC_COLUMNS} from documents
            where knowledge_base_id = ?
              and coalesce(source_sha256, content_hash) = ?
              and deleted_at is null
              {exclude_clause}
            order by created_at asc, id asc
            limit 1
            """,
            params,
        )
        return _map_document(row)

    def find_live_document_by_markdown_sha(
        self, knowledge_base_id: str, markdown_sha256: str
    ) -> Document | None:
        row = fetch_one(
            self.connection,
            f"""
            select {_DOC_COLUMNS} from documents
            where knowledge_base_id = ?
              and markdown_sha256 = ?
              and deleted_at is null
            order by created_at asc, id asc
            limit 1
            """,
            (knowledge_base_id, markdown_sha256),
        )
        return _map_document(row)

    def list_retrieval_sources(
        self,
        knowledge_base_id: str,
        *,
        pipeline_version: str | None = None,
    ) -> list[dict[str, Any]]:
        """The currently published generation, including the old pointer during replacement.

        LightRAG references are external, untrusted provenance. Callers must map them back to a
        durable source generation before returning the reference or placing its chunk in context.
        """
        pipeline_clause = ""
        params: tuple[Any, ...] = (knowledge_base_id,)
        if pipeline_version is not None:
            pipeline_clause = "and d.index_pipeline_version = ?"
            params = (*params, pipeline_version)
        return fetch_all(
            self.connection,
            f"""
            select d.id, d.knowledge_base_id,
                   coalesce(v.file_name, d.file_name) as file_name,
                   coalesce(v.file_type, d.file_type) as file_type,
                   coalesce(v.mime_type, d.mime_type) as mime_type,
                   coalesce(v.storage_key, d.storage_key) as storage_key,
                   d.indexed_sha256 as content_hash, d.indexed_sha256 as source_sha256,
                   d.indexed_sha256,
                   d.index_document_id,
                   ('kb-' || d.knowledge_base_id || '--doc-' || d.id || '--' ||
                    substr(d.indexed_sha256, 1, 16) || '.md') as lightrag_file_source
            from documents d
            join knowledge_bases kb on kb.id = d.knowledge_base_id
            left join knowledge_document_source_versions v
              on v.document_id = d.id and v.source_sha256 = d.indexed_sha256
            where d.knowledge_base_id = ?
              and kb.deleted_at is null
              and kb.status = 'active'
              and kb.index_status = 'ready'
              and d.deleted_at is null
              and d.indexed_sha256 is not null
              and d.index_document_id is not null
              {pipeline_clause}
            order by 1
            """,
            params,
        )

    def update_document(
        self,
        knowledge_base_id: str,
        document_id: str,
        *,
        file_name: str,
        metadata: dict[str, Any],
        now: str,
    ) -> Document | None:
        execute(
            self.connection,
            """
            update documents
            set file_name = ?, metadata = ?, updated_at = ?
            where id = ? and knowledge_base_id = ? and deleted_at is null
            """,
            (file_name, json_param(self.connection, metadata), now, document_id, knowledge_base_id),
        )
        return self.get_document(knowledge_base_id, document_id)

    def get_citation_source(self, document_id: str, source_sha256: str) -> dict[str, Any] | None:
        """Resolve the exact immutable original captured by a citation.

        Soft-deleted rows remain available until storage GC, but retrieval never sees them.
        """
        return fetch_one(
            self.connection,
            """
            select document_id as id, knowledge_base_id, file_name, file_type, mime_type,
                   storage_key as source_storage_key, source_sha256
            from knowledge_document_source_versions
            where document_id = ? and source_sha256 = ?
            limit 1
            """,
            (document_id, source_sha256),
        )

    def soft_delete_document(self, knowledge_base_id: str, document_id: str, now: str) -> bool:
        cursor = execute(
            self.connection,
            """
            update documents
            set deleted_at = ?, updated_at = ?
            where id = ? and knowledge_base_id = ? and deleted_at is null
            """,
            (now, now, document_id, knowledge_base_id),
        )
        return rowcount(cursor) > 0

    # build worker status transitions --------------------------------------------

    def snapshot_documents(self, knowledge_base_id: str) -> list[dict]:
        """The build's input snapshot: live documents at trigger time (deleted excluded)."""
        rows = fetch_all(
            self.connection,
            """
            select id, file_name, file_type, mime_type, storage_key, content_hash
            from documents
            where knowledge_base_id = ? and deleted_at is null
            order by created_at asc, id asc
            """,
            (knowledge_base_id,),
        )
        return [
            {
                "id": str(row["id"]),
                "fileName": str(row["file_name"]),
                "fileType": str(row["file_type"]),
                "storageKey": str(row["storage_key"]),
                "mimeType": str(row["mime_type"]) if row.get("mime_type") is not None else None,
                "contentHash": (
                    str(row["content_hash"]) if row.get("content_hash") is not None else None
                ),
            }
            for row in rows
        ]

    def set_parse_status(
        self, document_id: str, status: str, *, error: str | None = None, now: str
    ) -> None:
        execute(
            self.connection,
            """
            update documents
            set parse_status = ?, parse_error = ?, last_error = ?, updated_at = ?
            where id = ?
            """,
            (status, error, error, now, document_id),
        )

    def set_index_status(
        self, document_id: str, status: str, *, error: str | None = None, now: str
    ) -> None:
        execute(
            self.connection,
            """
            update documents
            set index_status = ?, last_error = ?, updated_at = ?
            where id = ?
            """,
            (status, error, now, document_id),
        )

    def set_index_result(
        self,
        document_id: str,
        *,
        status: str,
        index_document_id: str | None,
        lightrag_track_id: str | None,
        indexed_sha256: str | None = None,
        pipeline_version: str | None = None,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            update documents
            set parse_status = case when ? = 'ready' then 'ready' else parse_status end,
                parse_error = case when ? = 'ready' then null else parse_error end,
                index_status = ?, lightrag_track_id = ?, index_document_id = ?,
                indexed_sha256 = ?, index_pipeline_version = ?,
                last_error = null, updated_at = ?
            where id = ?
            """,
            (
                status,
                status,
                status,
                lightrag_track_id,
                index_document_id,
                indexed_sha256,
                pipeline_version,
                now,
                document_id,
            ),
        )

    def set_source_sha(self, document_id: str, source_sha256: str, now: str) -> None:
        execute(
            self.connection,
            """
            update documents
            set source_sha256 = ?, content_hash = coalesce(content_hash, ?), updated_at = ?
            where id = ?
            """,
            (source_sha256, source_sha256, now, document_id),
        )
        execute(
            self.connection,
            """
            insert into knowledge_document_source_versions (
              document_id, source_sha256, knowledge_base_id, file_name, file_type, mime_type,
              storage_key, object_bucket, file_size_bytes, created_at
            )
            select id, ?, knowledge_base_id, file_name, file_type, mime_type,
                   storage_key, object_bucket, file_size_bytes, ?
            from documents where id = ?
            on conflict (document_id, source_sha256) do nothing
            """,
            (source_sha256, now, document_id),
        )

    def set_markdown_artifact(
        self,
        document_id: str,
        *,
        source_sha256: str,
        storage_key: str,
        markdown_sha256: str,
        now: str,
    ) -> None:
        execute(
            self.connection,
            """
            insert into knowledge_document_markdown_artifacts (
              document_id, source_sha256, markdown_storage_key, markdown_sha256,
              created_at, updated_at
            ) values (?, ?, ?, ?, ?, ?)
            on conflict (document_id, source_sha256) do update set
              markdown_storage_key = excluded.markdown_storage_key,
              markdown_sha256 = excluded.markdown_sha256,
              updated_at = excluded.updated_at
            """,
            (document_id, source_sha256, storage_key, markdown_sha256, now, now),
        )
        execute(
            self.connection,
            """
            update documents
            set markdown_storage_key = ?, markdown_sha256 = ?, parse_status = 'ready',
                parse_error = null, last_error = null, updated_at = ?
            where id = ?
            """,
            (storage_key, markdown_sha256, now, document_id),
        )

    def clear_index_result(self, document_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update documents
            set index_document_id = null, lightrag_track_id = null,
                indexed_sha256 = null, index_pipeline_version = null,
                index_status = 'stale', updated_at = ?
            where id = ?
            """,
            (now, document_id),
        )

    def clear_pending_index_track(self, document_id: str, now: str) -> None:
        execute(
            self.connection,
            """
            update documents
            set lightrag_track_id = null, updated_at = ?
            where id = ?
            """,
            (now, document_id),
        )

    def set_lightrag_track_id(self, document_id: str, track_id: str, now: str) -> None:
        """Persist the ingestion track id as soon as LightRAG accepts the insert.

        The 409 conflict self-heal needs this even when ingestion later times out:
        the track id resolves the previous doc id for deletion.
        """
        execute(
            self.connection,
            """
            update documents
            set lightrag_track_id = ?, updated_at = ?
            where id = ?
            """,
            (track_id, now, document_id),
        )

    def list_deleted(self, limit: int) -> list[tuple[str, list[str]]]:
        rows = fetch_all(
            self.connection,
            """
            select id, storage_key, markdown_storage_key from documents
            where deleted_at is not null
              and index_document_id is null
            order by deleted_at asc limit ?
            """,
            (limit,),
        )
        deleted: list[tuple[str, list[str]]] = []
        for row in rows:
            document_id = str(row["id"])
            source_rows = fetch_all(
                self.connection,
                "select storage_key from knowledge_document_source_versions where document_id = ?",
                (document_id,),
            )
            artifact_rows = fetch_all(
                self.connection,
                """
                select markdown_storage_key from knowledge_document_markdown_artifacts
                where document_id = ?
                """,
                (document_id,),
            )
            keys = {
                str(value)
                for value in (row["storage_key"], row.get("markdown_storage_key"))
                if value is not None
            }
            keys.update(str(item["storage_key"]) for item in source_rows)
            keys.update(str(item["markdown_storage_key"]) for item in artifact_rows)
            deleted.append((document_id, sorted(keys)))
        return deleted

    def hard_delete_document(self, document_id: str) -> None:
        execute(self.connection, "delete from documents where id = ?", (document_id,))

    # knowledge-base purge (GC) ---------------------------------------------------
    # These ignore deleted_at: when a knowledge base is purged, every object it ever held must be
    # reclaimed -- soft-deleted documents and never-completed upload sessions included.

    def list_object_keys_for_kb(self, knowledge_base_id: str) -> list[str]:
        """Every object key the knowledge base may own: document bodies plus upload-session
        objects (an `initiated` session may have an uploaded-but-never-completed orphan object)."""
        doc_rows = fetch_all(
            self.connection,
            "select storage_key from documents where knowledge_base_id = ?",
            (knowledge_base_id,),
        )
        session_rows = fetch_all(
            self.connection,
            "select object_key from document_upload_sessions where knowledge_base_id = ?",
            (knowledge_base_id,),
        )
        keys = [str(row["storage_key"]) for row in doc_rows]
        version_rows = fetch_all(
            self.connection,
            """
            select storage_key from knowledge_document_source_versions
            where knowledge_base_id = ?
            """,
            (knowledge_base_id,),
        )
        sync_artifact_rows = fetch_all(
            self.connection,
            """
            select a.markdown_storage_key
            from knowledge_document_markdown_artifacts a
            join documents d on d.id = a.document_id
            where d.knowledge_base_id = ?
            """,
            (knowledge_base_id,),
        )
        markdown_rows = fetch_all(
            self.connection,
            """
            select markdown_storage_key from documents
            where knowledge_base_id = ? and markdown_storage_key is not null
            """,
            (knowledge_base_id,),
        )
        keys += [str(row["object_key"]) for row in session_rows]
        keys += [str(row["storage_key"]) for row in version_rows]
        keys += [str(row["markdown_storage_key"]) for row in sync_artifact_rows]
        keys += [str(row["markdown_storage_key"]) for row in markdown_rows]
        return keys


def _map_document(row: dict[str, Any] | None) -> Document | None:
    if not row:
        return None
    return Document(
        id=str(row["id"]),
        knowledgeBaseId=str(row["knowledge_base_id"]),
        fileName=str(row["file_name"]),
        fileType=str(row["file_type"]),
        mimeType=str(row["mime_type"]) if row["mime_type"] is not None else None,
        fileSizeBytes=int(row["file_size_bytes"]),
        storageKey=str(row["storage_key"]),
        contentHash=str(row["content_hash"]) if row["content_hash"] is not None else None,
        sourceSha=(str(row["source_sha256"]) if row.get("source_sha256") is not None else None),
        indexedSha=(str(row["indexed_sha256"]) if row.get("indexed_sha256") is not None else None),
        indexDocumentId=(
            str(row["index_document_id"]) if row.get("index_document_id") is not None else None
        ),
        indexPipelineVersion=(
            str(row["index_pipeline_version"])
            if row.get("index_pipeline_version") is not None
            else None
        ),
        parseStatus=str(row["parse_status"]),
        indexStatus=str(row["index_status"]),
        parseError=str(row["parse_error"]) if row.get("parse_error") is not None else None,
        lastError=str(row["last_error"]) if row.get("last_error") is not None else None,
        metadata=json_load(row["metadata"]),
        createdAt=str(row["created_at"]),
        updatedAt=str(row["updated_at"]),
    )


def _map_session(row: dict[str, Any] | None) -> UploadSession | None:
    if not row:
        return None
    return UploadSession(
        id=str(row["id"]),
        knowledge_base_id=str(row["knowledge_base_id"]),
        document_id=str(row["document_id"]),
        replaces_document_id=(
            str(row["replaces_document_id"])
            if row.get("replaces_document_id") is not None
            else None
        ),
        actor_user_id=str(row["actor_user_id"]),
        file_name=str(row["file_name"]),
        file_type=str(row["file_type"]),
        content_type=str(row["content_type"]) if row["content_type"] is not None else None,
        file_size_bytes=int(row["file_size_bytes"]),
        object_bucket=str(row["object_bucket"]),
        object_key=str(row["object_key"]),
        status=str(row["status"]),
        expires_at=str(row["expires_at"]),
    )

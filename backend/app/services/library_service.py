from __future__ import annotations

import re
import unicodedata
import zipfile
from datetime import datetime, timedelta, timezone
from io import BytesIO
from urllib.parse import quote
from uuid import uuid4
from xml.etree import ElementTree

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import DatabaseConnection
from app.domain.audit import AuditCategory, AuditOperationType, AuditResource
from app.domain.auth import Principal
from app.domain.library import (
    LibraryCompleteUploadRequest,
    LibraryCompleteUploadResult,
    LibraryCompleteUploadsRequest,
    LibraryCompleteUploadsResponse,
    LibraryDeletedResponse,
    LibraryDownloadResponse,
    LibraryFile,
    LibraryFileRecord,
    LibraryFileType,
    LibraryFileListResponse,
    LibraryPreviewResponse,
    LibraryRenameRequest,
    LibrarySort,
    LibrarySpace,
    LibrarySpacesResponse,
    LibraryUploadSessionRecord,
    LibraryUploadUrlRequest,
    LibraryUploadUrlResult,
    LibraryUploadUrlResponse,
    LibraryUploadUrlsRequest,
    LibraryUploadUrlsResponse,
)
from app.services._sql import is_unique_violation
from app.services.audit_service import AuditService, changes
from app.services.library_access_service import LibraryAccessService, LibraryAction
from app.services.library_repository import LibraryRepository
from app.services.object_store import ObjectStore, remove_if_present


_IMAGE_MIME_PREFIX = "image/"
_TEXT_MIME_PREFIX = "text/"
_INLINE_TEXT_MIME = {
    "application/json",
    "text/csv",
    "text/markdown",
    "text/plain",
}
_INLINE_TEXT_EXTENSIONS = {"txt", "md", "csv", "json"}
_PDF_MIME = "application/pdf"
_DOCX_EXTENSIONS = {"docx"}
_FILE_TYPE_BY_EXT = {
    "jpg": "image",
    "jpeg": "image",
    "png": "image",
    "webp": "image",
}
_DOCUMENT_EXTENSIONS = {"pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "md", "csv"}
_IMAGE_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
_ARCHIVE_EXTENSIONS = {"zip", "rar"}
_MAX_BYTES_BY_GROUP = {
    "document": 20 * 1024**2,
    "image": 10 * 1024**2,
    "archive": 50 * 1024**2,
}
_MIME_BY_EXTENSION = {
    "pdf": {"application/pdf"},
    "doc": {"application/msword", "application/octet-stream"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xls": {"application/vnd.ms-excel", "application/octet-stream"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "ppt": {"application/vnd.ms-powerpoint", "application/octet-stream"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    "txt": {"text/plain"},
    "md": {"text/markdown", "text/plain"},
    "csv": {"text/csv", "text/plain", "application/csv"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "png": {"image/png"},
    "webp": {"image/webp"},
    "zip": {"application/zip", "application/x-zip-compressed", "application/octet-stream"},
    "rar": {"application/vnd.rar", "application/x-rar-compressed", "application/octet-stream"},
}


class LibraryService:
    def __init__(
        self, connection: DatabaseConnection, store: ObjectStore, settings: Settings
    ) -> None:
        self.connection = connection
        self.store = store
        self.settings = settings
        self.repo = LibraryRepository(connection)
        self.access = LibraryAccessService(connection)

    def list_spaces(self, principal: Principal) -> LibrarySpacesResponse:
        items: list[LibrarySpace] = []
        for space_type in ("personal", "team"):
            access = self.access.space_access(principal, space_type, allow_unavailable=True)
            owner_key = (
                principal.user_id if space_type == "personal" else str(principal.active_tenant_id)
            )
            usage = self.repo.get_usage(space_type, owner_key)
            remaining = max(
                access.quota_bytes - usage["usedBytes"] - usage["reservedBytes"],
                0,
            )
            items.append(
                LibrarySpace(
                    spaceType=space_type,
                    status=access.status,
                    quotaBytes=access.quota_bytes,
                    usedBytes=usage["usedBytes"],
                    reservedBytes=usage["reservedBytes"],
                    remainingBytes=remaining,
                    breakdown=self.repo.usage_breakdown(space_type, owner_key),
                    capabilities=access.capabilities,
                )
            )
        return LibrarySpacesResponse(items=items)

    def list_files(
        self,
        principal: Principal,
        *,
        keyword: str | None,
        file_type: str,
        sort: LibrarySort,
        page: int,
        page_size: int,
        lifecycle: str = "permanent",
        session_id: str | None = None,
        space_type: str = "personal",
    ) -> LibraryFileListResponse:
        access = self.access.require(principal, space_type, LibraryAction.LIST)
        owner_key = principal.user_id if space_type == "personal" else str(access.tenant_id)
        normalized_type = None if file_type == "all" else file_type
        items, total = self.repo.list_files(
            space_type=space_type,
            owner_key=owner_key,
            keyword=keyword.strip() if keyword else None,
            file_type=normalized_type,
            sort=sort,
            limit=page_size,
            offset=(page - 1) * page_size,
            lifecycle=lifecycle,
            chat_session_id=session_id,
            now=_now_iso() if lifecycle == "temporary" else None,
        )
        return LibraryFileListResponse(
            items=[
                _to_item(
                    file,
                    capabilities=self.access.capabilities_for(
                        access, uploaded_by_user_id=file.uploadedByUserId
                    ),
                )
                for file in items
            ],
            total=total,
            page=page,
            pageSize=page_size,
        )

    def create_upload_url(
        self,
        principal: Principal,
        request: LibraryUploadUrlRequest,
    ) -> LibraryUploadUrlResponse:
        if request.spaceType == "team":
            access = self.access.require(principal, "team", LibraryAction.UPLOAD)
        else:
            access = self.access.require(principal, "personal", LibraryAction.UPLOAD)
        tenant_id = str(principal.active_tenant_id)
        return self._allocate_upload(
            principal.user_id,
            tenant_id,
            access=access,
            file_name=request.fileName,
            mime_type=request.mimeType,
            file_size_bytes=request.fileSizeBytes,
        )

    def _allocate_upload(
        self,
        user_id: str,
        tenant_id: str,
        *,
        access,
        file_name: str,
        mime_type: str | None,
        file_size_bytes: int,
    ) -> LibraryUploadUrlResponse:
        if file_size_bytes <= 0:
            raise ApiError(400, "LIBRARY_INVALID_SIZE", "fileSizeBytes must be positive")
        safe_name = _safe_file_name(file_name)
        extension = _extension(safe_name)
        _validate_declared_format(extension, mime_type, file_size_bytes)
        file_type = _resolve_file_type(safe_name, mime_type)
        file_id = f"file_{uuid4().hex}"
        session_id = f"upl_{uuid4().hex}"
        owner_key = user_id if access.space_type == "personal" else tenant_id
        object_key = _object_key(access.space_type, tenant_id, user_id, file_id, safe_name)
        now = _now_iso()
        expires = _now_plus_ttl(self.settings.presigned_url_ttl_seconds)

        owner_user_id = user_id if access.space_type == "personal" else None
        owner_tenant_id = tenant_id if access.space_type == "team" else None
        self.repo.ensure_usage(
            space_type=access.space_type,
            owner_key=owner_key,
            owner_user_id=owner_user_id,
            owner_tenant_id=owner_tenant_id,
            now=now,
        )
        if not self.repo.reserve_bytes(
            space_type=access.space_type,
            owner_key=owner_key,
            amount=file_size_bytes,
            quota=access.quota_bytes,
            now=now,
        ):
            self.connection.rollback()
            raise ApiError(413, "LIBRARY_QUOTA_EXCEEDED", "Library space quota would be exceeded")
        self.repo.create_upload_session(
            session_id=session_id,
            file_id=file_id,
            user_id=user_id,
            tenant_id=tenant_id,
            space_type=access.space_type,
            owner_user_id=owner_user_id,
            owner_tenant_id=owner_tenant_id,
            uploaded_by_user_id=user_id,
            original_name=file_name,
            safe_name=safe_name,
            requested_name=file_name,
            mime_type=mime_type,
            file_type=file_type,
            extension=extension,
            file_size_bytes=file_size_bytes,
            storage_bucket=self.store.bucket,
            storage_object_key=object_key,
            content_hash=None,
            reserved_bytes=file_size_bytes,
            expires_at=expires,
            now=now,
        )
        try:
            upload_url = self.store.presigned_put_url(
                object_key,
                expires=timedelta(seconds=self.settings.presigned_url_ttl_seconds),
                content_type=mime_type,
                content_length=file_size_bytes,
            )
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()

        suggested_name = _available_name(
            safe_name,
            self.repo.list_display_names(access.space_type, owner_key),
        )

        headers = {"Content-Type": mime_type} if mime_type else {}
        return LibraryUploadUrlResponse(
            uploadSessionId=session_id,
            fileId=file_id,
            uploadUrl=upload_url,
            headers=headers,
            objectKey=object_key,
            expiresAt=expires,
            spaceType=access.space_type,
            nameConflict=suggested_name != safe_name,
            suggestedName=suggested_name,
        )

    def complete_upload(
        self,
        principal: Principal,
        request: LibraryCompleteUploadRequest,
        *,
        request_id: str = "library",
    ) -> LibraryFile:
        user_id, tenant_id = self._owner(principal)
        session = self._load_session(request.uploadSessionId, user_id, tenant_id)
        if request.lifecycle == "temporary" and session.spaceType != "personal":
            self._fail_upload_session(session)
            raise ApiError(
                400,
                "LIBRARY_TEAM_TEMPORARY_FORBIDDEN",
                "Chat temporary attachments must use personal space",
            )
        try:
            access = self.access.require(principal, session.spaceType, LibraryAction.UPLOAD)
            owner_key = session.ownerUserId or session.ownerTenantId
            if owner_key is None:
                raise ApiError(500, "LIBRARY_OWNER_INVALID", "Upload session owner is invalid")
            usage = self.repo.get_usage(session.spaceType, owner_key)
            if access.quota_bytes <= 0 or (
                usage["usedBytes"] + usage["reservedBytes"] > access.quota_bytes
            ):
                raise ApiError(
                    409,
                    "LIBRARY_QUOTA_CHANGED",
                    "Current Library quota no longer permits upload completion",
                )
            self._verify_uploaded_object(session)
        except Exception:
            self._fail_upload_session(session)
            raise

        if request.lifecycle == "temporary":
            source, lifecycle = "chat_upload", "temporary"
            expires_at: str | None = _now_plus_ttl(self.settings.chat_attachment_retention_seconds)
        else:
            source, lifecycle, expires_at = "library", "permanent", None
        record = self._persist_completed_file(
            session,
            principal=principal,
            request_id=request_id,
            source=source,
            lifecycle=lifecycle,
            expires_at=expires_at,
        )
        return self._to_item_for_principal(principal, record)

    def create_upload_urls(
        self, principal: Principal, request: LibraryUploadUrlsRequest
    ) -> LibraryUploadUrlsResponse:
        results: list[LibraryUploadUrlResult] = []
        for item in request.items:
            try:
                results.append(
                    LibraryUploadUrlResult(
                        status="created", item=self.create_upload_url(principal, item)
                    )
                )
            except ApiError as exc:
                self.connection.rollback()
                results.append(LibraryUploadUrlResult(status="failed", error=_error_dict(exc)))
        return LibraryUploadUrlsResponse(items=results)

    def complete_uploads(
        self,
        principal: Principal,
        request: LibraryCompleteUploadsRequest,
        *,
        request_id: str = "library",
    ) -> LibraryCompleteUploadsResponse:
        results: list[LibraryCompleteUploadResult] = []
        for item in request.items:
            try:
                results.append(
                    LibraryCompleteUploadResult(
                        status="completed",
                        item=self.complete_upload(principal, item, request_id=request_id),
                    )
                )
            except ApiError as exc:
                self.connection.rollback()
                results.append(LibraryCompleteUploadResult(status="failed", error=_error_dict(exc)))
        return LibraryCompleteUploadsResponse(items=results)

    def promote_file(self, principal: Principal, file_id: str) -> LibraryFile:
        """Promote a temporary chat file to a permanent library file with no byte copy (§10)."""
        user_id, tenant_id = self._owner(principal)
        self.access.require(principal, "personal", LibraryAction.PROMOTE)
        current = self.repo.get_file(user_id, tenant_id, file_id)
        if current is None:
            raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
        if (
            current.lifecycle != "temporary"
            or current.expiresAt is None
            or _expired(current.expiresAt)
        ):
            raise ApiError(
                409,
                "LIBRARY_FILE_NOT_PROMOTABLE",
                "File is not a promotable temporary file (expired, already permanent, or deleted)",
            )
        owner_key = user_id
        final_name = _available_name(
            current.displayName,
            self.repo.list_display_names("personal", owner_key),
        )
        try:
            self.repo.claim_name(
                space_type="personal",
                owner_key=owner_key,
                normalized_name=_normalized_name(final_name),
                file_id=file_id,
                now=_now_iso(),
            )
        except Exception as exc:
            if not is_unique_violation(exc):
                raise
            self.connection.rollback()
            raise ApiError(
                409, "LIBRARY_NAME_CONFLICT", "Library file name already exists"
            ) from exc
        if final_name != current.displayName:
            self.repo.update_file_name(
                file_id,
                display_name=final_name,
                normalized_name=_normalized_name(final_name),
                safe_name=_safe_file_name(final_name),
                now=_now_iso(),
            )
        record = self.repo.promote_file(user_id, tenant_id, file_id, _now_iso())
        if record is None:
            # Distinguish a missing/deleted file (404) from a non-promotable one (409): expired,
            # already permanent. The expiry guard lives in promote_file's SQL where clause.
            if self.repo.get_file(user_id, tenant_id, file_id) is None:
                raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
            raise ApiError(
                409,
                "LIBRARY_FILE_NOT_PROMOTABLE",
                "File is not a promotable temporary file (expired, already permanent, or deleted)",
            )
        self.connection.commit()
        return self._to_item_for_principal(principal, record)

    def _load_session(
        self, upload_session_id: str, user_id: str, tenant_id: str
    ) -> LibraryUploadSessionRecord:
        """Load and validate an upload session for completion (owner, status, expiry, size).

        Shared by the library and chat complete-upload paths; the lifecycle/routing decision is
        made by each caller after this returns.
        """
        session = self.repo.get_upload_session(upload_session_id)
        if session is None:
            raise ApiError(404, "LIBRARY_UPLOAD_SESSION_NOT_FOUND", "Upload session not found")
        if session.uploadedByUserId != user_id or session.tenantId != tenant_id:
            raise ApiError(404, "LIBRARY_UPLOAD_SESSION_NOT_FOUND", "Upload session not found")
        if session.status != "initiated":
            raise ApiError(409, "LIBRARY_UPLOAD_SESSION_NOT_ACTIVE", "Upload session is not active")
        if _expired(session.expiresAt):
            self._fail_upload_session(session, status="expired")
            raise ApiError(409, "LIBRARY_UPLOAD_SESSION_EXPIRED", "Upload session has expired")
        return session

    def _verify_uploaded_object(self, session: LibraryUploadSessionRecord) -> None:
        stat = self.store.stat(session.storageObjectKey)
        if stat.size != session.fileSizeBytes:
            raise ApiError(
                400,
                "LIBRARY_UPLOAD_SIZE_MISMATCH",
                "Uploaded object size does not match the declared size",
                {"declared": session.fileSizeBytes, "actual": stat.size},
            )
        data = self.store.read(session.storageObjectKey, max_bytes=session.fileSizeBytes)
        _validate_actual_format(session.extension, data)

    def _fail_upload_session(
        self, session: LibraryUploadSessionRecord, *, status: str = "failed"
    ) -> None:
        now = _now_iso()
        object_removed = remove_if_present(self.store, session.storageObjectKey)
        owner_key = session.ownerUserId or session.ownerTenantId
        if owner_key is not None and session.status == "initiated":
            self.repo.release_reserved_bytes(
                space_type=session.spaceType,
                owner_key=owner_key,
                amount=session.reservedBytes,
                now=now,
            )
            next_status = status if object_removed or status == "failed" else "failed"
            self.repo.set_upload_session_status(session.id, next_status, now)
            self.connection.commit()

    def _persist_completed_file(
        self,
        session: LibraryUploadSessionRecord,
        *,
        principal: Principal,
        request_id: str,
        source: str,
        lifecycle: str,
        expires_at: str | None,
        chat_session_id: str | None = None,
    ) -> LibraryFileRecord:
        owner_key = session.ownerUserId or session.ownerTenantId
        if owner_key is None:
            raise ApiError(500, "LIBRARY_OWNER_INVALID", "Upload session owner is invalid")
        for _ in range(10):
            now = _now_iso()
            final_name = (
                _available_name(
                    session.requestedName,
                    self.repo.list_display_names(session.spaceType, owner_key),
                )
                if lifecycle == "permanent" or session.spaceType == "team"
                else session.requestedName
            )
            normalized_name = _normalized_name(final_name)
            try:
                record = self.repo.create_file(
                    file_id=session.fileId,
                    user_id=session.uploadedByUserId,
                    tenant_id=session.tenantId,
                    space_type=session.spaceType,
                    owner_user_id=session.ownerUserId,
                    owner_tenant_id=session.ownerTenantId,
                    uploaded_by_user_id=session.uploadedByUserId,
                    original_name=final_name,
                    safe_name=_safe_file_name(final_name),
                    display_name=final_name,
                    normalized_name=normalized_name,
                    mime_type=session.mimeType,
                    file_type=session.fileType,
                    extension=session.extension,
                    size_bytes=session.fileSizeBytes,
                    storage_bucket=session.storageBucket,
                    storage_object_key=session.storageObjectKey,
                    # A single presigned PUT only gives us object size/ETag, not a verifiable sha256.
                    # Keep client-declared contentHash off the durable file row until a trusted
                    # server-side hash pass exists.
                    content_hash=None,
                    preview_supported=_preview_supported(
                        session.mimeType, session.extension, session.fileType
                    ),
                    metadata={},
                    now=now,
                    source=source,
                    lifecycle=lifecycle,
                    expires_at=expires_at,
                    chat_session_id=chat_session_id,
                )
                if lifecycle == "permanent" or session.spaceType == "team":
                    self.repo.claim_name(
                        space_type=session.spaceType,
                        owner_key=owner_key,
                        normalized_name=normalized_name,
                        file_id=session.fileId,
                        now=now,
                    )
                if not self.repo.complete_reserved_bytes(
                    space_type=session.spaceType,
                    owner_key=owner_key,
                    amount=session.reservedBytes,
                    now=now,
                ):
                    raise ApiError(
                        409,
                        "LIBRARY_QUOTA_RESERVATION_LOST",
                        "Upload quota reservation is no longer available",
                    )
                self.repo.set_upload_session_status(session.id, "completed", now, completed=True)
                AuditService(self.connection).record(
                    AuditService(self.connection).context(principal, request_id),
                    category=AuditCategory.LIBRARY,
                    action="library.upload_completed",
                    operation_type=AuditOperationType.UPLOAD,
                    resource=AuditResource(
                        type="library_file", id=record.id, name=record.displayName
                    ),
                    metadata={
                        "spaceType": record.spaceType,
                        "fileName": record.displayName,
                        "mimeType": record.mimeType,
                        "fileSizeBytes": record.sizeBytes,
                    },
                )
                self.connection.commit()
                return record
            except Exception as exc:  # noqa: BLE001 - completion/name concurrency boundary
                if not is_unique_violation(exc):
                    self.connection.rollback()
                    self._fail_upload_session(session)
                    raise
                self.connection.rollback()
                if self.repo.get_file_by_id(session.fileId) is not None:
                    raise ApiError(
                        409,
                        "LIBRARY_UPLOAD_ALREADY_COMPLETED",
                        "Upload session has already been completed",
                    ) from exc
        self._fail_upload_session(session)
        raise ApiError(409, "LIBRARY_NAME_CONFLICT", "Could not allocate a unique Library name")

    def resolve_turn_attachments(
        self, principal: Principal, session_id: str, file_ids: list[str], *, bind: bool
    ) -> list[LibraryFileRecord]:
        """Load and §5-authorize the files a turn references, auto-binding temporaries (§7.3).

        Authorization by kind:
        - permanent: readable by its owner in any session.
        - temporary, unbound (chat_session_id is null): readable by its owner. With bind=True it is
          bound to this session (once); with bind=False (pre-flight) it is allowed as-is.
        - temporary, bound to this session: readable while not expired.
        - temporary, bound to another session: rejected.

        Raises rather than silently dropping an unauthorized id, so a turn never half-references
        files it was denied. bind=True commits the binding.
        """
        records: list[LibraryFileRecord] = []
        user_id, tenant_id = self._owner(principal)
        bound_any = False
        for file_id in file_ids:
            record = self.repo.get_file_by_id(file_id)
            if record is None:
                raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", f"Library file not found: {file_id}")
            if record.spaceType == "personal":
                if record.ownerUserId != user_id:
                    raise ApiError(
                        404, "LIBRARY_FILE_NOT_FOUND", f"Library file not found: {file_id}"
                    )
            elif record.ownerTenantId != tenant_id:
                raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", f"Library file not found: {file_id}")
            _require_agent_compatible(record)
            self.access.require(
                principal,
                record.spaceType,
                LibraryAction.USE_AGENT,
                uploaded_by_user_id=record.uploadedByUserId,
                hide_missing=True,
            )
            if record.lifecycle == "temporary":
                if record.expiresAt is None or _expired(record.expiresAt):
                    raise ApiError(
                        403, "LIBRARY_FILE_FORBIDDEN", f"Attachment has expired: {file_id}"
                    )
                if record.chatSessionId is None and bind:
                    # First turn to reference this file binds it to this session (once). A
                    # concurrent turn in another session may win the race, so re-read the outcome.
                    bound = self.repo.bind_temporary_file_session(
                        user_id, tenant_id, file_id, session_id, _now_iso()
                    )
                    record = bound or self.repo.get_file(user_id, tenant_id, file_id) or record
                    bound_any = True
                if record.chatSessionId is not None and record.chatSessionId != session_id:
                    raise ApiError(
                        403,
                        "LIBRARY_FILE_FORBIDDEN",
                        f"Attachment is bound to another session: {file_id}",
                    )
            records.append(record)
        if bound_any:
            self.connection.commit()
        return records

    @staticmethod
    def attachment_snapshot(records: list[LibraryFileRecord], attached_at: str) -> list[dict]:
        """Denormalized per-turn provenance snapshot (§9). Self-contained by design."""
        return [
            {
                "fileId": record.id,
                "name": record.displayName,
                "mimeType": record.mimeType,
                "sizeBytes": record.sizeBytes,
                "lifecycle": record.lifecycle,
                "spaceType": record.spaceType,
                "ownerTenantId": record.ownerTenantId,
                "uploadedByUserId": record.uploadedByUserId,
                "attachedAt": attached_at,
            }
            for record in records
        ]

    def attachment_delivery_url(
        self, principal: Principal, turn_id: str, record: LibraryFileRecord
    ) -> str:
        token = f"ldc_{uuid4().hex}"
        expires_at = _now_plus_ttl(self.settings.attachment_delivery_url_ttl_seconds)
        self.repo.create_delivery_capability(
            token=token,
            file_id=record.id,
            actor_user_id=principal.user_id,
            tenant_id=str(principal.active_tenant_id),
            turn_id=turn_id,
            max_uses=3,
            expires_at=expires_at,
            now=_now_iso(),
        )
        base = (self.settings.library_delivery_public_base_url or "").rstrip("/")
        path = f"/api/v1/library/delivery/{token}"
        return f"{base}{path}" if base else path

    def consume_delivery_capability(
        self, token: str, *, request_id: str = "library-delivery"
    ) -> tuple[LibraryFileRecord, bytes]:
        capability = self.repo.get_delivery_capability(token)
        if capability is None:
            raise ApiError(404, "LIBRARY_DELIVERY_NOT_FOUND", "Library delivery link not found")
        principal = Principal(
            user_id=str(capability["actor_user_id"]),
            email="delivery@internal.invalid",
            active_tenant_id=str(capability["tenant_id"]),
        )
        record = self.repo.get_file_by_id(str(capability["file_id"]))
        if record is None:
            raise ApiError(410, "LIBRARY_DELIVERY_REVOKED", "Library delivery link was revoked")
        _require_agent_compatible(record)
        if record.spaceType == "personal":
            if record.ownerUserId != principal.user_id:
                raise ApiError(410, "LIBRARY_DELIVERY_REVOKED", "Library delivery link was revoked")
        elif record.ownerTenantId != principal.active_tenant_id:
            raise ApiError(410, "LIBRARY_DELIVERY_REVOKED", "Library delivery link was revoked")
        try:
            self.access.require(
                principal,
                record.spaceType,
                LibraryAction.USE_AGENT,
                uploaded_by_user_id=record.uploadedByUserId,
            )
        except ApiError as exc:
            raise ApiError(
                410, "LIBRARY_DELIVERY_REVOKED", "Library delivery link was revoked"
            ) from exc
        if not self.repo.consume_delivery_capability(token, _now_iso()):
            self.connection.rollback()
            raise ApiError(410, "LIBRARY_DELIVERY_EXPIRED", "Library delivery link has expired")
        try:
            content = self.store.read(record.storageObjectKey, max_bytes=record.sizeBytes)
            self._record_read_audit(
                principal,
                record,
                request_id=request_id,
                action="library.agent_delivery_consumed",
                metadata={"turnId": str(capability["turn_id"])},
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return record, content

    async def agent_file_text(self, record: LibraryFileRecord) -> str:
        _require_agent_compatible(record)
        content = self.store.read(record.storageObjectKey, max_bytes=20 * 1024 * 1024)
        try:
            if record.extension in _DOCX_EXTENSIONS:
                text = _extract_docx_text(content)
            elif _is_text_preview(record.mimeType, record.extension):
                text = content.decode("utf-8-sig")
            elif record.extension in {"pdf", "xlsx", "pptx", *_IMAGE_EXTENSIONS}:
                from app.clients.docling_client import DoclingClient
                text = await DoclingClient(self.settings).convert_to_markdown(
                    record.displayName, content
                )
            else:
                raise ApiError(
                    422, "LIBRARY_AGENT_FORMAT_UNSUPPORTED",
                    "This file format cannot be parsed for Agent reading",
                )
        except (UnicodeError, ValueError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            raise ApiError(422, "LIBRARY_FILE_PARSE_FAILED", "File text could not be parsed") from exc
        if not text.strip():
            raise ApiError(422, "LIBRARY_FILE_PARSE_FAILED", "File contains no readable text")
        return text

    def preview_file(
        self, principal: Principal, file_id: str, *, request_id: str = "library"
    ) -> LibraryPreviewResponse:
        record = self._require_file(principal, file_id)
        if not _record_preview_supported(record):
            return LibraryPreviewResponse(previewType="unsupported")
        if record.extension in _DOCX_EXTENSIONS:
            content = _extract_docx_text(
                self.store.read(record.storageObjectKey, max_bytes=10 * 1024 * 1024)
            )
            self._record_read_audit(
                principal,
                record,
                request_id=request_id,
                action="library.content_read",
                metadata={"disposition": "preview"},
            )
            self.connection.commit()
            return LibraryPreviewResponse(
                previewType="text",
                content=content,
                mimeType=record.mimeType,
            )
        if _is_text_preview(record.mimeType, record.extension):
            content = self.store.read(record.storageObjectKey, max_bytes=1024 * 1024).decode(
                "utf-8", errors="replace"
            )
            self._record_read_audit(
                principal,
                record,
                request_id=request_id,
                action="library.content_read",
                metadata={"disposition": "preview"},
            )
            self.connection.commit()
            return LibraryPreviewResponse(
                previewType="text",
                content=content,
                mimeType=record.mimeType,
            )
        return LibraryPreviewResponse(
            previewType="url",
            url=f"/api/v1/library/files/{record.id}/content?disposition=inline",
            mimeType=record.mimeType,
            expiresAt=None,
        )

    def download_file(self, principal: Principal, file_id: str) -> LibraryDownloadResponse:
        record = self._require_file(principal, file_id)
        return LibraryDownloadResponse(
            downloadUrl=f"/api/v1/library/files/{record.id}/content?disposition=attachment",
            expiresAt=None,
        )

    def read_file_content(
        self,
        principal: Principal,
        file_id: str,
        *,
        disposition: str = "attachment",
        request_id: str = "library",
    ) -> tuple[LibraryFileRecord, bytes]:
        record = self._require_file(principal, file_id)
        content = self.store.read(record.storageObjectKey, max_bytes=record.sizeBytes)
        self._record_read_audit(
            principal,
            record,
            request_id=request_id,
            action="library.content_read",
            metadata={"disposition": disposition},
        )
        self.connection.commit()
        return record, content

    def _record_read_audit(
        self,
        principal: Principal,
        record: LibraryFileRecord,
        *,
        request_id: str,
        action: str,
        metadata: dict[str, str],
    ) -> None:
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.LIBRARY,
            action=action,
            operation_type=AuditOperationType.READ,
            resource=AuditResource(type="library_file", id=record.id, name=record.displayName),
            metadata={
                "spaceType": record.spaceType,
                "fileName": record.displayName,
                "mimeType": record.mimeType,
                "fileSizeBytes": record.sizeBytes,
                **metadata,
            },
        )

    def rename_file(
        self,
        principal: Principal,
        file_id: str,
        request: LibraryRenameRequest,
        *,
        request_id: str = "library",
    ) -> LibraryFile:
        record = self._require_file(principal, file_id, action=LibraryAction.RENAME)
        if record.lifecycle != "permanent":
            raise ApiError(409, "LIBRARY_FILE_NOT_RENAMEABLE", "Temporary files cannot be renamed")
        display_name = _safe_file_name(request.name)
        _validate_declared_format(_extension(display_name), record.mimeType, record.sizeBytes)
        normalized_name = _normalized_name(display_name)
        if normalized_name == record.normalizedName:
            return self._to_item_for_principal(principal, record)
        owner_key = record.ownerUserId or record.ownerTenantId
        assert owner_key is not None
        self.repo.release_name_claim(file_id)
        try:
            self.repo.claim_name(
                space_type=record.spaceType,
                owner_key=owner_key,
                normalized_name=normalized_name,
                file_id=file_id,
                now=_now_iso(),
            )
        except Exception as exc:
            self.connection.rollback()
            if is_unique_violation(exc):
                raise ApiError(
                    409, "LIBRARY_NAME_CONFLICT", "Library file name already exists"
                ) from exc
            raise
        self.repo.update_file_name(
            file_id,
            display_name=display_name,
            normalized_name=normalized_name,
            safe_name=display_name,
            now=_now_iso(),
        )
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.LIBRARY,
            action="library.rename",
            operation_type=AuditOperationType.UPDATE,
            resource=AuditResource(type="library_file", id=file_id, name=display_name),
            changes=changes(
                {"name": record.displayName},
                {"name": display_name},
                {"name"},
            ),
        )
        self.connection.commit()
        updated = self.repo.get_file_by_id(file_id)
        assert updated is not None
        return self._to_item_for_principal(principal, updated)

    def delete_file(
        self, principal: Principal, file_id: str, *, request_id: str = "library"
    ) -> LibraryDeletedResponse:
        record = self._require_file(principal, file_id, action=LibraryAction.DELETE)
        owner_key = record.ownerUserId or record.ownerTenantId
        assert owner_key is not None
        now = _now_iso()
        deleted = self.repo.soft_delete_file(file_id, now)
        if not deleted:
            raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
        self.repo.release_name_claim(file_id)
        self.repo.release_used_bytes(
            space_type=record.spaceType,
            owner_key=owner_key,
            amount=record.sizeBytes,
            now=now,
        )
        access = self.access.space_access(
            principal,
            record.spaceType,
            uploaded_by_user_id=record.uploadedByUserId,
            allow_unavailable=True,
        )
        audit = AuditService(self.connection)
        audit.record(
            audit.context(principal, request_id),
            category=AuditCategory.LIBRARY,
            action="library.delete",
            operation_type=AuditOperationType.DELETE,
            resource=AuditResource(type="library_file", id=file_id, name=record.displayName),
            metadata={
                "spaceType": record.spaceType,
                "fileName": record.displayName,
                "mimeType": record.mimeType,
                "fileSizeBytes": record.sizeBytes,
                "readOnlyAdmin": record.spaceType == "team" and access.status == "read_only",
            },
        )
        self.connection.commit()
        return LibraryDeletedResponse(id=file_id)

    def expire_stale_sessions(self) -> int:
        """Expire timed-out upload sessions and remove their orphan objects."""
        now = _now_iso()
        sessions = self.repo.list_expired_upload_sessions(now)
        reclaimed = 0
        for session in sessions:
            if not remove_if_present(self.store, session.storageObjectKey):
                continue
            owner_key = session.ownerUserId or session.ownerTenantId
            if owner_key is not None and session.status == "initiated":
                self.repo.release_reserved_bytes(
                    space_type=session.spaceType,
                    owner_key=owner_key,
                    amount=session.reservedBytes,
                    now=now,
                )
            self.repo.set_upload_session_status(session.id, "expired", now)
            reclaimed += 1
        self.connection.commit()
        return reclaimed

    def purge_deleted_files(self, limit: int = 100) -> int:
        deleted = self.repo.list_deleted(limit)
        purged = 0
        for file_id, storage_key in deleted:
            if remove_if_present(self.store, storage_key):
                self.repo.hard_delete_file(file_id)
                purged += 1
        self.connection.commit()
        return purged

    def purge_expired_temporary_files(self, limit: int = 100) -> int:
        """Temporary-file GC pass (§12.2).

        Hard-delete the rows of expired temporary attachments and remove their objects (the
        default: §9's provenance snapshot already preserves history, so the row need not linger).
        Promotion clears expires_at, so promoted files are excluded. There is no on-disk delivery
        copy to reclaim -- delivery is content-only (§12.3).
        """
        now = _now_iso()
        expired = self.repo.list_expired_temporary_files(now, limit)
        purged = 0
        for file_id, storage_key in expired:
            record = self.repo.get_file_by_id(file_id)
            if record is None:
                continue
            owner_key = record.ownerUserId or record.ownerTenantId
            if owner_key is None:
                continue
            if self.repo.soft_delete_file(file_id, now):
                self.repo.release_used_bytes(
                    space_type=record.spaceType,
                    owner_key=owner_key,
                    amount=record.sizeBytes,
                    now=now,
                )
                self.connection.commit()
            if remove_if_present(self.store, storage_key):
                self.repo.hard_delete_file(file_id)
                purged += 1
        self.connection.commit()
        return purged

    def usage_reconciliation(self) -> dict[str, object]:
        items = self.repo.usage_reconciliation_rows(_now_iso())
        for item in items:
            item["matches"] = (
                item["ledgerUsedBytes"] == item["actualUsedBytes"]
                and item["ledgerReservedBytes"] == item["actualReservedBytes"]
            )
        return {"items": items, "mismatchCount": sum(not item["matches"] for item in items)}

    def _require_file(
        self,
        principal: Principal,
        file_id: str,
        *,
        action: LibraryAction = LibraryAction.READ,
    ) -> LibraryFileRecord:
        user_id, tenant_id = self._owner(principal)
        record = self.repo.get_file_by_id(file_id)
        if record is None:
            raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
        if record.spaceType == "personal" and record.ownerUserId != user_id:
            raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
        if record.spaceType == "team" and record.ownerTenantId != tenant_id:
            raise ApiError(404, "LIBRARY_FILE_NOT_FOUND", "Library file not found")
        self.access.require(
            principal,
            record.spaceType,
            action,
            uploaded_by_user_id=record.uploadedByUserId,
            hide_missing=action in {LibraryAction.READ, LibraryAction.USE_AGENT},
        )
        return record

    def _to_item_for_principal(
        self, principal: Principal, record: LibraryFileRecord
    ) -> LibraryFile:
        access = self.access.space_access(
            principal,
            record.spaceType,
            uploaded_by_user_id=record.uploadedByUserId,
            allow_unavailable=True,
        )
        return _to_item(record, capabilities=access.capabilities)

    @staticmethod
    def _owner(principal: Principal) -> tuple[str, str]:
        if principal.active_tenant_id is None:
            raise ApiError(401, "AUTH_UNAUTHORIZED", "Missing active tenant")
        return principal.user_id, str(principal.active_tenant_id)


def _to_item(
    record: LibraryFileRecord, *, capabilities: dict[str, bool] | None = None
) -> LibraryFile:
    return LibraryFile(
        id=record.id,
        name=record.displayName,
        mimeType=record.mimeType,
        type=record.fileType,
        sizeBytes=record.sizeBytes,
        sizeLabel=_size_label(record.sizeBytes),
        lifecycle=record.lifecycle,
        expiresAt=record.expiresAt,
        updatedAt=record.updatedAt,
        createdAt=record.createdAt,
        previewSupported=_record_preview_supported(record),
        spaceType=record.spaceType,
        ownerUserId=record.ownerUserId,
        ownerTenantId=record.ownerTenantId,
        uploadedByUserId=record.uploadedByUserId,
        capabilities=capabilities or {},
    )


def _object_key(space_type: str, tenant_id: str, user_id: str, file_id: str, safe_name: str) -> str:
    if space_type == "team":
        return f"library/{tenant_id}/team/{file_id}/{_ascii_key_name(safe_name)}"
    return f"library/users/{user_id}/{file_id}/{_ascii_key_name(safe_name)}"


def _ascii_key_name(safe_name: str) -> str:
    """ASCII-only name for the storage object key.

    Non-ASCII object keys (e.g. Chinese filenames) force PyJWT to emit \\uXXXX escapes inside the
    signed presigned-URL token; clients that re-encode the URL strip those backslashes and corrupt
    the signature (401). The display name is kept separately as original_name, so the key name is
    cosmetic -- collapse anything outside [A-Za-z0-9._-] to '_' and preserve the extension.
    """
    stem, dot, ext = safe_name.rpartition(".")
    base = stem if dot else safe_name
    ext = ext if dot else ""
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._-") or "file"
    ext = re.sub(r"[^A-Za-z0-9]+", "", ext)
    return f"{base}.{ext}" if ext else base


def _safe_file_name(file_name: str) -> str:
    safe = file_name.replace("\\", "/").split("/")[-1].strip()
    safe = re.sub(r"[\x00-\x1f\x7f]", "", safe)
    if not safe or safe in {".", ".."}:
        raise ApiError(400, "LIBRARY_INVALID_FILE_NAME", "Invalid file name")
    return safe


def _normalized_name(file_name: str) -> str:
    return unicodedata.normalize("NFKC", file_name).strip().casefold()


def _available_name(file_name: str, existing_names: list[str]) -> str:
    existing = {_normalized_name(name) for name in existing_names}
    if _normalized_name(file_name) not in existing:
        return file_name
    stem, dot, extension = file_name.rpartition(".")
    if not dot or not stem:
        stem, dot, extension = file_name, "", ""
    for suffix in range(1, 10_001):
        candidate = f"{stem} ({suffix}){dot}{extension}"
        if _normalized_name(candidate) not in existing:
            return candidate
    raise ApiError(409, "LIBRARY_NAME_CONFLICT", "Could not allocate a unique Library name")


def _extension(file_name: str) -> str | None:
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[1].lower() or None


def _resolve_file_type(file_name: str, mime_type: str | None) -> LibraryFileType:
    ext = _extension(file_name)
    if ext in _FILE_TYPE_BY_EXT:
        return _FILE_TYPE_BY_EXT[ext]
    if mime_type and mime_type.startswith(_IMAGE_MIME_PREFIX):
        return "image"
    return "file"


def _validate_declared_format(
    extension: str | None, mime_type: str | None, file_size_bytes: int
) -> None:
    if extension in _DOCUMENT_EXTENSIONS:
        group = "document"
    elif extension in _IMAGE_EXTENSIONS:
        group = "image"
    elif extension in _ARCHIVE_EXTENSIONS:
        group = "archive"
    else:
        raise ApiError(400, "LIBRARY_UNSUPPORTED_FORMAT", "File extension is not supported")
    if file_size_bytes > _MAX_BYTES_BY_GROUP[group]:
        raise ApiError(
            413,
            "LIBRARY_FILE_TOO_LARGE",
            "File exceeds the size limit for its format group",
            {"maxBytes": _MAX_BYTES_BY_GROUP[group]},
        )
    if mime_type is not None:
        normalized_mime = mime_type.split(";", 1)[0].strip().lower()
        if normalized_mime not in _MIME_BY_EXTENSION[str(extension)]:
            raise ApiError(
                400,
                "LIBRARY_MIME_MISMATCH",
                "Declared MIME type does not match the file extension",
            )


def _validate_actual_format(extension: str | None, data: bytes) -> None:
    valid = False
    if extension == "pdf":
        valid = data.startswith(b"%PDF-")
    elif extension in {"jpg", "jpeg"}:
        valid = data.startswith(b"\xff\xd8\xff")
    elif extension == "png":
        valid = data.startswith(b"\x89PNG\r\n\x1a\n")
    elif extension == "webp":
        valid = len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    elif extension in {"doc", "xls", "ppt"}:
        valid = data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    elif extension in {"docx", "xlsx", "pptx"}:
        valid = _valid_ooxml(extension, data)
    elif extension == "zip":
        valid = _valid_zip(data)
    elif extension == "rar":
        valid = data.startswith((b"Rar!\x1a\x07\x00", b"Rar!\x1a\x07\x01\x00"))
    elif extension in {"txt", "md", "csv"}:
        valid = _valid_bounded_text(data)
    if not valid:
        raise ApiError(
            400,
            "LIBRARY_CONTENT_MISMATCH",
            "Uploaded content does not match the declared file format",
        )


def _valid_zip(data: bytes) -> bool:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            return bool(entries) and len(entries) <= 10_000
    except zipfile.BadZipFile:
        return False


def _valid_ooxml(extension: str, data: bytes) -> bool:
    prefix = {"docx": "word/", "xlsx": "xl/", "pptx": "ppt/"}[extension]
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            names = archive.namelist()
            return (
                len(names) <= 10_000
                and "[Content_Types].xml" in names
                and any(name.startswith(prefix) for name in names)
            )
    except zipfile.BadZipFile:
        return False


def _valid_bounded_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return False
    return all(char in "\n\r\t" or ord(char) >= 0x20 for char in text)


def _error_dict(exc: ApiError) -> dict[str, object]:
    value: dict[str, object] = {"code": exc.code, "message": exc.message}
    if exc.details:
        value["details"] = exc.details
    return value


def _preview_supported(
    mime_type: str | None, extension: str | None, file_type: LibraryFileType
) -> bool:
    if file_type == "image":
        return True
    if mime_type == _PDF_MIME or extension == "pdf":
        return True
    if extension in _DOCX_EXTENSIONS:
        return True
    if mime_type in _INLINE_TEXT_MIME:
        return True
    if mime_type and mime_type.startswith(_TEXT_MIME_PREFIX):
        return True
    return extension in _INLINE_TEXT_EXTENSIONS


def _record_preview_supported(record: LibraryFileRecord) -> bool:
    return _preview_supported(record.mimeType, record.extension, record.fileType)


def _is_text_preview(mime_type: str | None, extension: str | None) -> bool:
    if mime_type == _PDF_MIME or extension == "pdf":
        return False
    if extension in _DOCX_EXTENSIONS:
        return True
    return _preview_supported(mime_type, extension, "file")


def _inline_content_disposition(file_name: str) -> str:
    fallback = re.sub(r'["\\]', "_", file_name)
    fallback = "".join(char if 0x20 <= ord(char) < 0x7F else "_" for char in fallback)
    fallback = fallback or "download"
    encoded = quote(file_name, safe="")
    return f"inline; filename=\"{fallback}\"; filename*=UTF-8''{encoded}"


def _attachment_content_disposition(file_name: str) -> str:
    return _inline_content_disposition(file_name).replace("inline;", "attachment;", 1)


def _size_label(size: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} B"
            return f"{value:.1f}".rstrip("0").rstrip(".") + f" {unit}"
        value /= 1024
    return f"{size} B"


def _extract_docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            xml = archive.read("word/document.xml")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise ApiError(400, "LIBRARY_PREVIEW_UNAVAILABLE", "DOCX preview is unavailable") from exc
    root = ElementTree.fromstring(xml)
    namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    paragraphs: list[str] = []
    for paragraph in root.iter(f"{namespace}p"):
        parts = [text.text or "" for text in paragraph.iter(f"{namespace}t")]
        line = "".join(parts).strip()
        if line:
            paragraphs.append(line)
    return "\n".join(paragraphs)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _now_plus_ttl(ttl_seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)).isoformat()


def _expired(value: str) -> bool:
    expires_at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at <= datetime.now(timezone.utc)


def _require_agent_compatible(record: LibraryFileRecord) -> None:
    if record.extension in _ARCHIVE_EXTENSIONS:
        raise ApiError(
            400,
            "LIBRARY_AGENT_FORMAT_UNSUPPORTED",
            "Archive files cannot be used as Agent attachments",
        )

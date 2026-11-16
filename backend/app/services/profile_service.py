from __future__ import annotations

from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import PurePosixPath
from uuid import uuid4
import warnings

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import Settings
from app.core.errors import ApiError
from app.db import open_database_connection
from app.domain.profile import CurrentUserProfile, UpdateCurrentUserProfileRequest
from app.services.object_store import ObjectStore, best_effort_remove, create_object_store
from app.services.profile_repository import ProfileRecord, ProfileRepository


_MIME_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}
_EXTENSION_FORMATS = {
    ".jpg": "JPEG",
    ".jpeg": "JPEG",
    ".png": "PNG",
    ".webp": "WEBP",
}


class ProfileService:
    def __init__(self, settings: Settings, object_store: ObjectStore | None = None) -> None:
        self.settings = settings
        self._object_store = object_store

    @property
    def avatar_max_upload_bytes(self) -> int:
        return self.settings.avatar_max_upload_bytes

    @property
    def object_store(self) -> ObjectStore:
        if self._object_store is None:
            try:
                self._object_store = create_object_store(self.settings)
            except ApiError as exc:
                if exc.code == "OBJECT_STORE_UNAVAILABLE":
                    raise _object_store_unavailable() from exc
                raise
        return self._object_store

    def get_profile(self, user_id: str) -> CurrentUserProfile:
        with open_database_connection(self.settings) as connection:
            record = ProfileRepository(connection).get(user_id)
        if not record:
            raise _user_not_found()
        return self._response(record)

    def update_profile(
        self,
        user_id: str,
        body: UpdateCurrentUserProfileRequest,
    ) -> CurrentUserProfile:
        fields = body.model_fields_set
        with open_database_connection(self.settings) as connection:
            repo = ProfileRepository(connection)
            repo.begin_write()
            current = repo.get(user_id, for_update=True)
            if not current:
                raise _user_not_found()
            if not repo.update_profile(
                user_id,
                update_name="name" in fields,
                name=body.name,
                update_preferred_locale="preferredLocale" in fields,
                preferred_locale=body.preferredLocale,
            ):
                raise _user_not_found()
            connection.commit()
        return self.get_profile(user_id)

    def upload_avatar(
        self,
        user_id: str,
        *,
        filename: str,
        content_type: str | None,
        data: bytes,
    ) -> CurrentUserProfile:
        if len(data) > self.settings.avatar_max_upload_bytes:
            raise ApiError(413, "AVATAR_TOO_LARGE", "Avatar file is too large")
        declared_format = _declared_format(filename, content_type)
        encoded = _normalize_avatar(
            data,
            declared_format=declared_format,
            max_pixels=self.settings.avatar_max_pixels,
            max_dimension=self.settings.avatar_max_dimension,
        )
        new_key = f"users/{user_id}/avatars/{uuid4().hex}.webp"

        try:
            self.object_store.put(new_key, encoded, content_type="image/webp")
        except Exception as exc:
            raise _object_store_unavailable() from exc

        old_key: str | None = None
        try:
            with open_database_connection(self.settings) as connection:
                repo = ProfileRepository(connection)
                repo.begin_write()
                current = repo.get(user_id, for_update=True)
                if not current:
                    raise _user_not_found()
                old_key = current.avatar_object_key
                if not repo.update_avatar_object_key(user_id, new_key):
                    raise _user_not_found()
                connection.commit()
        except Exception:
            best_effort_remove(self.object_store, new_key)
            raise

        if old_key:
            best_effort_remove(self.object_store, old_key)
        return self.get_profile(user_id)

    def delete_avatar(self, user_id: str) -> CurrentUserProfile:
        old_key: str | None = None
        with open_database_connection(self.settings) as connection:
            repo = ProfileRepository(connection)
            repo.begin_write()
            current = repo.get(user_id, for_update=True)
            if not current:
                raise _user_not_found()
            old_key = current.avatar_object_key
            if old_key and not repo.update_avatar_object_key(user_id, None):
                raise _user_not_found()
            connection.commit()

        if old_key:
            best_effort_remove(self.object_store, old_key)
        return self.get_profile(user_id)

    def _response(self, record: ProfileRecord) -> CurrentUserProfile:
        avatar_url: str | None = None
        expires_at: str | None = None
        if record.avatar_object_key:
            ttl = timedelta(seconds=self.settings.avatar_url_ttl_seconds)
            now = datetime.now(timezone.utc)
            try:
                avatar_url = self.object_store.presigned_get_url(
                    record.avatar_object_key,
                    expires=ttl,
                )
            except Exception as exc:
                raise _object_store_unavailable() from exc
            expires_at = _iso_utc(now + ttl)

        return CurrentUserProfile(
            id=record.id,
            email=record.email,
            name=record.name,
            preferredLocale=record.preferred_locale,
            avatarUrl=avatar_url,
            avatarUrlExpiresAt=expires_at,
            updatedAt=_iso_utc(record.updated_at),
        )


def _declared_format(filename: str, content_type: str | None) -> str:
    normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
    normalized_name = filename.replace("\\", "/")
    extension = PurePosixPath(normalized_name).suffix.lower()
    mime_format = _MIME_FORMATS.get(normalized_type)
    extension_format = _EXTENSION_FORMATS.get(extension)
    if not mime_format or not extension_format or mime_format != extension_format:
        raise ApiError(
            415,
            "AVATAR_UNSUPPORTED_TYPE",
            "Avatar must be a JPEG, PNG, or WebP image",
        )
    return mime_format


def _normalize_avatar(
    data: bytes,
    *,
    declared_format: str,
    max_pixels: int,
    max_dimension: int,
) -> bytes:
    if not data:
        raise _invalid_image()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as probe:
                actual_format = str(probe.format or "").upper()
                if actual_format not in {"JPEG", "PNG", "WEBP"}:
                    raise ApiError(
                        415,
                        "AVATAR_UNSUPPORTED_TYPE",
                        "Avatar must be a JPEG, PNG, or WebP image",
                    )
                if actual_format != declared_format:
                    raise ApiError(
                        415,
                        "AVATAR_UNSUPPORTED_TYPE",
                        "Avatar content does not match its declared type",
                    )
                width, height = probe.size
                if width < 1 or height < 1 or width * height > max_pixels:
                    raise _invalid_image()
                if bool(getattr(probe, "is_animated", False)):
                    raise ApiError(
                        415,
                        "AVATAR_UNSUPPORTED_TYPE",
                        "Animated avatars are not supported",
                    )
                probe.verify()

            with Image.open(BytesIO(data)) as source:
                source.load()
                oriented = ImageOps.exif_transpose(source)
                target_side = min(max_dimension, oriented.width, oriented.height)
                mode = "RGBA" if "A" in oriented.getbands() else "RGB"
                converted = oriented.convert(mode)
                normalized = ImageOps.fit(
                    converted,
                    (target_side, target_side),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
                output = BytesIO()
                normalized.save(output, format="WEBP", quality=85, method=6)
                return output.getvalue()
    except ApiError:
        raise
    except (
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise _invalid_image() from exc


def _invalid_image() -> ApiError:
    return ApiError(400, "AVATAR_INVALID_IMAGE", "Avatar is not a valid image")


def _user_not_found() -> ApiError:
    return ApiError(404, "USER_NOT_FOUND", "User not found")


def _object_store_unavailable() -> ApiError:
    return ApiError(503, "OBJECT_STORE_UNAVAILABLE", "Object storage is unavailable")


def _iso_utc(value: object) -> str:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

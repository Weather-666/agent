from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.security import hash_password, verify_password
from app.db import open_database_connection
from app.domain.auth import PasswordResetLocale
from app.services.email_service import EmailSendError, EmailService
from app.services.password_reset_repository import PasswordResetRepository


logger = logging.getLogger(__name__)

PASSWORD_RESET_REQUEST_MESSAGE = (
    "如果该邮箱已注册，密码重置验证码将发送到该邮箱"
)
PASSWORD_RESET_SUCCESS_MESSAGE = "密码重置成功，请重新登录"


class PasswordResetService:
    def __init__(self, settings: Settings, email_service: EmailService) -> None:
        self.settings = settings
        self.email_service = email_service

    def request_code(self, email: str, locale: PasswordResetLocale = "zh-CN") -> str:
        normalized = email.strip().lower()
        now = datetime.now(timezone.utc)
        created_at = now.isoformat()
        code_id: str | None = None
        user_id: str | None = None
        recipient: str | None = None
        code: str | None = None

        with open_database_connection(self.settings) as connection:
            repo = PasswordResetRepository(connection)
            repo.begin_write()
            user = repo.find_user_by_email_for_update(normalized)
            if not user or user.status != "active":
                connection.commit()
                return PASSWORD_RESET_REQUEST_MESSAGE

            latest = repo.latest_available_code(user.id, for_update=False)
            cooldown_cutoff = now - timedelta(
                seconds=self.settings.password_reset_cooldown_seconds
            )
            if latest and _parse_datetime(latest.created_at) > cooldown_cutoff:
                connection.commit()
                return PASSWORD_RESET_REQUEST_MESSAGE

            code = f"{secrets.randbelow(1_000_000):06d}"
            code_id = f"password_reset_{uuid4().hex}"
            user_id = user.id
            recipient = user.email
            repo.invalidate_available_codes(user.id, created_at)
            repo.create_code(
                code_id=code_id,
                user_id=user.id,
                code_hash=hash_password(code),
                expires_at=(
                    now + timedelta(seconds=self.settings.password_reset_code_ttl_seconds)
                ).isoformat(),
                created_at=created_at,
            )
            connection.commit()

        try:
            self.email_service.send_password_reset_code(
                recipient=str(recipient),
                code=str(code),
                locale=locale,
            )
        except EmailSendError as exc:
            self._invalidate_failed_delivery(str(code_id))
            logger.error(
                "Password reset email delivery failed",
                extra={"user_id": user_id, "error_type": type(exc).__name__},
            )
            raise ApiError(
                503,
                "EMAIL_SEND_FAILED",
                "密码重置邮件发送失败，请稍后重试",
            ) from exc

        return PASSWORD_RESET_REQUEST_MESSAGE

    def confirm(self, email: str, code: str, new_password: str) -> str:
        if len(new_password) < 8:
            raise ApiError(422, "AUTH_PASSWORD_TOO_SHORT", "新密码至少需要8位")

        normalized = email.strip().lower()
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        with open_database_connection(self.settings) as connection:
            repo = PasswordResetRepository(connection)
            repo.begin_write()
            user = repo.find_user_by_email_for_update(normalized)
            if not user or user.status != "active":
                connection.commit()
                raise _invalid_code_error()

            reset_code = repo.latest_available_code(user.id, for_update=True)
            if (
                not reset_code
                or reset_code.attempt_count >= self.settings.password_reset_max_attempts
            ):
                connection.commit()
                raise _invalid_code_error()

            if _parse_datetime(reset_code.expires_at) <= now:
                repo.invalidate_code(reset_code.id, now_iso)
                connection.commit()
                raise _invalid_code_error()

            if not verify_password(code, reset_code.code_hash):
                repo.record_failed_attempt(
                    reset_code.id,
                    attempted_at=now_iso,
                    maximum=self.settings.password_reset_max_attempts,
                )
                connection.commit()
                raise _invalid_code_error()

            if not repo.occupy_code(
                reset_code.id,
                used_at=now_iso,
                maximum=self.settings.password_reset_max_attempts,
            ):
                connection.commit()
                raise _invalid_code_error()

            if not repo.update_password(user.id, hash_password(new_password), now_iso):
                raise _invalid_code_error()
            repo.revoke_refresh_tokens(user.id, now_iso)
            connection.commit()

        return PASSWORD_RESET_SUCCESS_MESSAGE

    def _invalidate_failed_delivery(self, code_id: str) -> None:
        with open_database_connection(self.settings) as connection:
            repo = PasswordResetRepository(connection)
            repo.begin_write()
            repo.invalidate_code(code_id, datetime.now(timezone.utc).isoformat())
            connection.commit()


def _invalid_code_error() -> ApiError:
    return ApiError(
        400,
        "AUTH_PASSWORD_RESET_CODE_INVALID",
        "验证码无效或已过期",
    )


def _parse_datetime(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)

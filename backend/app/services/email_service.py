from __future__ import annotations

import html
import smtplib
import ssl
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage

from app.core.config import Settings
from app.domain.auth import PasswordResetLocale


@dataclass(frozen=True)
class PasswordResetEmailTemplate:
    subject: str
    text: str
    html: str


PASSWORD_RESET_EMAIL_TEMPLATES: dict[PasswordResetLocale, PasswordResetEmailTemplate] = {
    "zh-CN": PasswordResetEmailTemplate(
        subject="WinWise 密码重置验证码",
        text=(
            "你正在重置 WinWise 登录密码。\n\n"
            "本次验证码为：{code}\n\n"
            "验证码10分钟内有效，请勿转发给他人。"
            "如果不是你本人操作，请忽略此邮件。"
        ),
        html=(
            "<html><body>"
            "<p>你正在重置 WinWise 登录密码。</p>"
            '<p>本次验证码为：<strong style="font-size: 24px; letter-spacing: 4px;">'
            "{code}</strong></p>"
            "<p>验证码10分钟内有效，请勿转发给他人。"
            "如果不是你本人操作，请忽略此邮件。</p>"
            "</body></html>"
        ),
    ),
    "en-US": PasswordResetEmailTemplate(
        subject="WinWise Password Reset Code",
        text=(
            "You are resetting your WinWise sign-in password.\n\n"
            "Your verification code is: {code}\n\n"
            "This code is valid for 10 minutes. Do not share it with anyone. "
            "If you did not request this, ignore this email."
        ),
        html=(
            "<html><body>"
            "<p>You are resetting your WinWise sign-in password.</p>"
            '<p>Your verification code is: <strong style="font-size: 24px; '
            'letter-spacing: 4px;">{code}</strong></p>'
            "<p>This code is valid for 10 minutes. Do not share it with anyone. "
            "If you did not request this, ignore this email.</p>"
            "</body></html>"
        ),
    ),
}


class EmailSendError(RuntimeError):
    pass


class EmailService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def send_password_reset_code(
        self,
        *,
        recipient: str,
        code: str,
        locale: PasswordResetLocale,
    ) -> None:
        server = self.settings.smtp_server
        username = self.settings.smtp_username
        password = self.settings.smtp_password
        from_address = self.settings.smtp_from_address
        if not all((server, username, password, from_address)) or not self.settings.smtp_use_ssl:
            raise EmailSendError("SMTP is not configured for SSL delivery")

        try:
            message = self._password_reset_message(
                recipient=recipient,
                code=code,
                from_address=str(from_address),
                locale=locale,
            )
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                host=str(server),
                port=self.settings.smtp_port,
                timeout=self.settings.smtp_timeout_seconds,
                context=context,
            ) as smtp:
                smtp.login(str(username), str(password))
                smtp.send_message(
                    message,
                    from_addr=str(from_address),
                    to_addrs=[recipient],
                )
        except (OSError, ValueError, smtplib.SMTPException) as exc:
            raise EmailSendError("Password reset email delivery failed") from exc

    def _password_reset_message(
        self,
        *,
        recipient: str,
        code: str,
        from_address: str,
        locale: PasswordResetLocale,
    ) -> EmailMessage:
        template = PASSWORD_RESET_EMAIL_TEMPLATES.get(
            locale,
            PASSWORD_RESET_EMAIL_TEMPLATES["zh-CN"],
        )
        message = EmailMessage()
        message["Subject"] = template.subject
        message["From"] = Address(
            display_name=self.settings.smtp_from_name or "WinWise",
            addr_spec=from_address,
        )
        message["To"] = recipient

        message.set_content(template.text.format(code=code))
        safe_code = html.escape(code)
        message.add_alternative(template.html.format(code=safe_code), subtype="html")
        return message

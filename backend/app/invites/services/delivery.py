from __future__ import annotations

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from functools import lru_cache
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit

from pydantic import (
    EmailStr,
    Field,
    SecretStr,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.config.settings import get_settings
from app.invites.models.invite import Invite

_PROTECTED_INVITE_DELIVERY_ENVIRONMENTS = frozenset({"dev", "staging", "prod"})


class InviteDeliveryConfigurationError(RuntimeError):
    """Raised when invite delivery is unsafe for the active environment."""


class InviteDeliverySettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="INVITE_DELIVERY__",
        extra="ignore",
    )

    provider: Literal["noop", "smtp"] = "noop"
    from_email: EmailStr | None = None
    subject: str = "You have been invited"
    accept_url_template: str | None = None
    smtp_host: str | None = None
    smtp_port: int = Field(default=587, gt=0, le=65535)
    smtp_username: str | None = None
    smtp_password: SecretStr | None = None
    smtp_timeout_seconds: float = Field(default=10.0, gt=0)
    smtp_use_tls: bool = False
    smtp_start_tls: bool = True

    @field_validator(
        "provider",
        "from_email",
        "subject",
        "accept_url_template",
        "smtp_host",
        "smtp_username",
        mode="before",
    )
    @classmethod
    def normalise_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalised = value.strip()
            return normalised or None
        return value

    @field_validator("smtp_password", mode="before")
    @classmethod
    def normalise_optional_secret(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalised = value.strip()
            return normalised or None
        return value

    @field_validator("subject")
    @classmethod
    def validate_subject(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("INVITE_DELIVERY__SUBJECT must not be blank")
        return value.strip()

    @field_validator("accept_url_template")
    @classmethod
    def validate_accept_url_template(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if "{token}" not in value:
            raise ValueError(
                "INVITE_DELIVERY__ACCEPT_URL_TEMPLATE must contain {token}"
            )
        parsed = urlsplit(value.replace("{token}", "token"))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "INVITE_DELIVERY__ACCEPT_URL_TEMPLATE must be an http(s) URL"
            )
        return value

    @model_validator(mode="after")
    def validate_smtp_provider(self) -> InviteDeliverySettings:
        if self.provider != "smtp":
            return self
        missing: list[str] = []
        if self.from_email is None:
            missing.append("INVITE_DELIVERY__FROM_EMAIL")
        if self.accept_url_template is None:
            missing.append("INVITE_DELIVERY__ACCEPT_URL_TEMPLATE")
        if self.smtp_host is None:
            missing.append("INVITE_DELIVERY__SMTP_HOST")
        if missing:
            raise ValueError(
                "INVITE_DELIVERY__PROVIDER=smtp requires: " + ", ".join(missing)
            )
        if self.smtp_use_tls and self.smtp_start_tls:
            raise ValueError(
                "INVITE_DELIVERY__SMTP_USE_TLS and "
                "INVITE_DELIVERY__SMTP_START_TLS cannot both be true"
            )
        has_username = self.smtp_username is not None
        has_password = self.smtp_password is not None
        if has_username != has_password:
            raise ValueError(
                "INVITE_DELIVERY__SMTP_USERNAME and "
                "INVITE_DELIVERY__SMTP_PASSWORD must be set together"
            )
        return self


class InviteTokenSink(Protocol):
    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        """Deliver raw invite token through an out-of-band channel."""


class NoOpInviteTokenSink:
    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        return None


class SmtpInviteTokenSink:
    def __init__(self, settings: InviteDeliverySettings) -> None:
        if settings.provider != "smtp":
            raise InviteDeliveryConfigurationError(
                "SmtpInviteTokenSink requires INVITE_DELIVERY__PROVIDER=smtp"
            )
        self.settings = settings

    async def deliver(self, *, invite: Invite, raw_token: str) -> None:
        message = build_invite_email_message(
            invite=invite,
            raw_token=raw_token,
            settings=self.settings,
        )
        await asyncio.to_thread(_send_smtp_message, message, self.settings)


_DEFAULT_INVITE_TOKEN_SINK = NoOpInviteTokenSink()


@lru_cache(maxsize=1)
def get_invite_delivery_settings() -> InviteDeliverySettings:
    return InviteDeliverySettings()


def get_invite_token_sink() -> InviteTokenSink:
    app_settings = get_settings()
    if not app_settings.outbox.invite_delivery_enabled:
        return _DEFAULT_INVITE_TOKEN_SINK

    delivery_settings = get_invite_delivery_settings()
    if delivery_settings.provider == "smtp":
        _ensure_protected_smtp_url_policy(
            delivery_settings,
            environment=app_settings.app.environment,
        )
        return SmtpInviteTokenSink(delivery_settings)
    _ensure_noop_allowed(
        environment=app_settings.app.environment,
        invite_delivery_enabled=app_settings.outbox.invite_delivery_enabled,
    )
    return _DEFAULT_INVITE_TOKEN_SINK


def build_invite_email_message(
    *,
    invite: Invite,
    raw_token: str,
    settings: InviteDeliverySettings,
) -> EmailMessage:
    if settings.from_email is None or settings.accept_url_template is None:
        raise InviteDeliveryConfigurationError("SMTP invite delivery is incomplete")
    accept_url = settings.accept_url_template.replace(
        "{token}",
        quote(raw_token, safe=""),
    )
    message = EmailMessage()
    message["From"] = str(settings.from_email)
    message["To"] = invite.email
    message["Subject"] = settings.subject
    message.set_content(_invite_email_body(invite=invite, accept_url=accept_url))
    return message


def _invite_email_body(*, invite: Invite, accept_url: str) -> str:
    role_value = getattr(invite.role, "value", invite.role)
    lines = [
        "You have been invited to join an organisation.",
        "",
        f"Role: {role_value}",
        "",
        "Open this invitation link to accept:",
        accept_url,
        "",
    ]
    if invite.expires_at is not None:
        lines.extend(
            [
                "This invitation expires at:",
                invite.expires_at.isoformat(),
                "",
            ]
        )
    lines.append("If you did not expect this invitation, ignore this email.")
    return "\n".join(str(line) for line in lines)


def _send_smtp_message(
    message: EmailMessage,
    settings: InviteDeliverySettings,
) -> None:
    if settings.smtp_host is None:
        raise InviteDeliveryConfigurationError("SMTP invite delivery host is missing")
    context = ssl.create_default_context()
    password = (
        settings.smtp_password.get_secret_value()
        if settings.smtp_password is not None
        else None
    )
    if settings.smtp_use_tls:
        with smtplib.SMTP_SSL(
            settings.smtp_host,
            settings.smtp_port,
            timeout=settings.smtp_timeout_seconds,
            context=context,
        ) as smtp:
            _authenticate_and_send(smtp, message, settings, password=password)
        return
    with smtplib.SMTP(
        settings.smtp_host,
        settings.smtp_port,
        timeout=settings.smtp_timeout_seconds,
    ) as smtp:
        if settings.smtp_start_tls:
            smtp.starttls(context=context)
        _authenticate_and_send(smtp, message, settings, password=password)


def _authenticate_and_send(
    smtp: smtplib.SMTP,
    message: EmailMessage,
    settings: InviteDeliverySettings,
    *,
    password: str | None,
) -> None:
    if settings.smtp_username is not None and password is not None:
        smtp.login(settings.smtp_username, password)
    smtp.send_message(message)


def _ensure_noop_allowed(
    *,
    environment: str,
    invite_delivery_enabled: bool,
) -> None:
    if not invite_delivery_enabled:
        return
    if environment not in _PROTECTED_INVITE_DELIVERY_ENVIRONMENTS:
        return
    raise InviteDeliveryConfigurationError(
        "INVITE_DELIVERY__PROVIDER=smtp is required when "
        "OUTBOX__INVITE_DELIVERY_ENABLED=true in dev/staging/prod"
    )


def _ensure_protected_smtp_url_policy(
    settings: InviteDeliverySettings,
    *,
    environment: str,
) -> None:
    if environment not in {"staging", "prod"}:
        return
    if settings.accept_url_template is None:
        raise InviteDeliveryConfigurationError("SMTP invite accept URL is missing")
    scheme = urlsplit(settings.accept_url_template.replace("{token}", "token")).scheme
    if scheme != "https":
        raise InviteDeliveryConfigurationError(
            f"INVITE_DELIVERY__ACCEPT_URL_TEMPLATE must use https:// in {environment}"
        )

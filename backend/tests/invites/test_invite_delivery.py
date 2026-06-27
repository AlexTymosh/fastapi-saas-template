from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.core.config.settings import get_settings
from app.invites.models.invite import Invite
from app.invites.services import delivery
from app.invites.services.delivery import (
    InviteDeliveryConfigurationError,
    InviteDeliverySettings,
    NoOpInviteTokenSink,
    SmtpInviteTokenSink,
    get_invite_delivery_settings,
    get_invite_token_sink,
)
from app.memberships.models.membership import MembershipRole
from tests.helpers.asyncio_runner import run_async

FERNET_TEST_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="


@pytest.fixture(autouse=True)
def clear_delivery_settings_cache():
    get_settings.cache_clear()
    get_invite_delivery_settings.cache_clear()
    yield
    get_settings.cache_clear()
    get_invite_delivery_settings.cache_clear()


def _set_dev_invite_delivery_baseline(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "dev")
    monkeypatch.setenv("OUTBOX__INVITE_DELIVERY_ENABLED", "true")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)


def _set_smtp_invite_delivery(monkeypatch) -> None:
    monkeypatch.setenv("INVITE_DELIVERY__PROVIDER", "smtp")
    monkeypatch.setenv("INVITE_DELIVERY__FROM_EMAIL", "invites@example.com")
    monkeypatch.setenv(
        "INVITE_DELIVERY__ACCEPT_URL_TEMPLATE",
        "https://app.example.test/invites/accept?token={token}",
    )
    monkeypatch.setenv("INVITE_DELIVERY__SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("INVITE_DELIVERY__SMTP_START_TLS", "false")


def test_local_invite_delivery_uses_noop_sink_by_default() -> None:
    sink = get_invite_token_sink()

    assert isinstance(sink, NoOpInviteTokenSink)


def test_noop_invite_delivery_treats_blank_sender_as_unset(monkeypatch) -> None:
    monkeypatch.setenv("INVITE_DELIVERY__PROVIDER", "noop")
    monkeypatch.setenv("INVITE_DELIVERY__FROM_EMAIL", "   ")

    settings = get_invite_delivery_settings()
    sink = get_invite_token_sink()

    assert settings.from_email is None
    assert isinstance(sink, NoOpInviteTokenSink)


def test_protected_invite_delivery_rejects_noop_provider(monkeypatch) -> None:
    _set_dev_invite_delivery_baseline(monkeypatch)

    with pytest.raises(InviteDeliveryConfigurationError, match="PROVIDER=smtp"):
        get_invite_token_sink()


def test_disabled_invite_delivery_uses_noop_before_provider_config(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "dev")
    monkeypatch.setenv("OUTBOX__INVITE_DELIVERY_ENABLED", "false")
    monkeypatch.setenv("INVITE_DELIVERY__PROVIDER", "smtp")
    monkeypatch.delenv("INVITE_DELIVERY__FROM_EMAIL", raising=False)
    monkeypatch.delenv("INVITE_DELIVERY__ACCEPT_URL_TEMPLATE", raising=False)
    monkeypatch.delenv("INVITE_DELIVERY__SMTP_HOST", raising=False)

    sink = get_invite_token_sink()

    assert isinstance(sink, NoOpInviteTokenSink)


def test_protected_invite_delivery_uses_smtp_provider(monkeypatch) -> None:
    _set_dev_invite_delivery_baseline(monkeypatch)
    _set_smtp_invite_delivery(monkeypatch)

    sink = get_invite_token_sink()

    assert isinstance(sink, SmtpInviteTokenSink)


def test_smtp_invite_delivery_requires_token_url_template() -> None:
    with pytest.raises(ValueError, match="ACCEPT_URL_TEMPLATE"):
        InviteDeliverySettings(
            provider="smtp",
            from_email="invites@example.com",
            accept_url_template="https://app.example.test/invites/accept",
            smtp_host="smtp.example.test",
        )


def test_smtp_invite_delivery_requires_sender_after_blank_normalisation() -> None:
    with pytest.raises(ValueError, match="INVITE_DELIVERY__FROM_EMAIL"):
        InviteDeliverySettings(
            provider="smtp",
            from_email="  ",
            accept_url_template="https://app.example.test/invites/{token}",
            smtp_host="smtp.example.test",
        )


def test_smtp_invite_delivery_sends_email(monkeypatch) -> None:
    sent: dict[str, object] = {}

    class FakeSMTP:
        def __init__(self, host: str, port: int, *, timeout: float) -> None:
            sent["host"] = host
            sent["port"] = port
            sent["timeout"] = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self, *, context) -> None:
            sent["starttls"] = context is not None

        def login(self, username: str, password: str) -> None:
            sent["login"] = (username, password)

        def send_message(self, message) -> None:
            sent["message"] = message

    monkeypatch.setattr(delivery.smtplib, "SMTP", FakeSMTP)
    settings = InviteDeliverySettings(
        provider="smtp",
        from_email="invites@example.com",
        accept_url_template="https://app.example.test/invites/{token}",
        smtp_host="smtp.example.test",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
        smtp_start_tls=True,
    )
    invite = Invite(
        email="new-user@example.com",
        role=MembershipRole.MEMBER,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )

    run_async(
        SmtpInviteTokenSink(settings).deliver(
            invite=invite,
            raw_token="raw token/+",
        )
    )

    assert sent["host"] == "smtp.example.test"
    assert sent["port"] == 587
    assert sent["starttls"] is True
    assert sent["login"] == ("smtp-user", "smtp-password")
    message = sent["message"]
    assert message["From"] == "invites@example.com"
    assert message["To"] == "new-user@example.com"
    assert "raw%20token%2F%2B" in message.get_content()
    assert "raw token/+" not in message.get_content()

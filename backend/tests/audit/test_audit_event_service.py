from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from starlette.requests import Request

from app.audit.context import AuditContext, build_audit_context_from_request
from app.audit.minimisation import minimise_ip_address, normalise_user_agent
from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.audit.services.audit_events import AuditEventService
from app.core.config.settings import AuditSettings
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security, pytest.mark.privacy]


def test_audit_service_persists_minimised_network_context(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = await AuditEventService(session).record_event(
                audit_context=AuditContext(
                    actor_user_id=None,
                    ip_address="127.0.0.1",
                    user_agent="pytest",
                ),
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type=AuditTargetType.ORGANISATION,
                target_id=uuid4(),
                metadata_json={"changed_fields": ["slug"]},
            )
            await session.commit()
            assert event.id is not None
            assert event.category == "tenant"
            assert event.metadata_json == {"changed_fields": ["slug"]}
            assert event.ip_address == "127.0.0.0/24"
            assert event.user_agent == "client:test"

    run_async(_run())


def test_build_audit_context_ignores_spoofed_xff_from_untrusted_client() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/example",
        "headers": [
            (b"user-agent", b"pytest-agent"),
            (b"x-forwarded-for", b"203.0.113.1"),
        ],
        "client": ("127.0.0.1", 32100),
    }
    request = Request(scope)
    actor_user_id = uuid4()

    context = build_audit_context_from_request(
        actor_user_id=actor_user_id, request=request
    )

    assert context.actor_user_id == actor_user_id
    assert context.ip_address == "127.0.0.1"
    assert context.user_agent == "pytest-agent"


def test_build_audit_context_uses_forwarded_ip_from_trusted_proxy() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/example",
        "headers": [
            (b"user-agent", b"pytest-agent"),
            (b"x-forwarded-for", b"203.0.113.1"),
        ],
        "client": ("127.0.0.1", 32100),
        "app": SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    rate_limiting=SimpleNamespace(
                        trust_proxy_headers=True,
                        trusted_proxy_cidrs=["127.0.0.1/32"],
                    )
                )
            )
        ),
    }
    request = Request(scope)
    actor_user_id = uuid4()

    context = build_audit_context_from_request(
        actor_user_id=actor_user_id, request=request
    )

    assert context.actor_user_id == actor_user_id
    assert context.ip_address == "203.0.113.1"
    assert context.user_agent == "pytest-agent"


def test_build_audit_context_drops_invalid_peer_host() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/example",
        "headers": [(b"user-agent", b"pytest-agent")],
        "client": ("local-test-socket", 32100),
    }
    request = Request(scope)

    context = build_audit_context_from_request(actor_user_id=None, request=request)

    assert context.ip_address is None
    assert minimise_ip_address(context.ip_address) is None


def test_build_audit_context_ignores_forwarded_ip_when_peer_host_is_invalid() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/example",
        "headers": [
            (b"user-agent", b"pytest-agent"),
            (b"x-forwarded-for", b"203.0.113.1"),
        ],
        "client": ("local-test-socket", 32100),
        "app": SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    rate_limiting=SimpleNamespace(
                        trust_proxy_headers=True,
                        trusted_proxy_cidrs=["127.0.0.1/32"],
                    )
                )
            )
        ),
    }
    request = Request(scope)

    context = build_audit_context_from_request(actor_user_id=None, request=request)

    assert context.ip_address is None


def test_build_audit_context_uses_injected_app_audit_settings() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/example",
        "headers": [(b"user-agent", b"pytest-agent")],
        "client": ("203.0.113.42", 32100),
        "app": SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    audit=AuditSettings(network_identifier_secret="x" * 32)
                )
            )
        ),
    }
    request = Request(scope)

    context = build_audit_context_from_request(actor_user_id=None, request=request)

    assert context.network_identifier_secret is not None
    minimised = minimise_ip_address(
        context.ip_address,
        secret=context.network_identifier_secret,
    )
    assert minimised is not None
    assert minimised.startswith("hmac:v1:")
    assert minimised != "203.0.113.0/24"


def test_audit_service_uses_context_network_identifier_secret(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = await AuditEventService(session).record_event(
                audit_context=AuditContext(
                    actor_user_id=None,
                    ip_address="203.0.113.42",
                    user_agent="pytest",
                    network_identifier_secret=AuditSettings(
                        network_identifier_secret="x" * 32
                    ).network_identifier_secret,
                ),
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type=AuditTargetType.ORGANISATION,
                target_id=uuid4(),
            )
            await session.commit()
            result = await session.execute(
                select(AuditEvent).where(AuditEvent.id == event.id)
            )
            saved = result.scalar_one()
            assert saved.ip_address is not None
            assert saved.ip_address.startswith("hmac:v1:")
            assert saved.ip_address != "203.0.113.0/24"

    run_async(_run())


def test_audit_ip_minimisation_supports_hmac_identifier() -> None:
    minimised = minimise_ip_address("203.0.113.42", secret="x" * 32)

    assert minimised is not None
    assert minimised.startswith("hmac:v1:")
    assert len(minimised) == 40
    assert "203.0.113.42" not in minimised


def test_audit_ip_minimisation_uses_network_without_secret() -> None:
    assert minimise_ip_address("203.0.113.42") == "203.0.113.0/24"
    assert (
        minimise_ip_address("2001:db8:abcd:1234:ffff::1") == "2001:db8:abcd:1234::/64"
    )


def test_user_agent_normalisation_does_not_store_full_header() -> None:
    raw = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
    )

    assert normalise_user_agent(raw) == "browser:chrome"
    assert normalise_user_agent(raw) != raw


def test_audit_service_normalises_user_agent_family(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = await AuditEventService(session).record_event(
                audit_context=AuditContext(
                    actor_user_id=None,
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
                    ),
                ),
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type=AuditTargetType.ORGANISATION,
                target_id=uuid4(),
            )
            await session.commit()
            result = await session.execute(
                select(AuditEvent).where(AuditEvent.id == event.id)
            )
            saved = result.scalar_one()
            assert saved.user_agent == "browser:chrome"

    run_async(_run())


def test_invalid_ip_address_is_not_persisted(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = await AuditEventService(session).record_event(
                audit_context=AuditContext(actor_user_id=None, ip_address="not-an-ip"),
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type=AuditTargetType.ORGANISATION,
                target_id=uuid4(),
            )
            await session.commit()
            result = await session.execute(
                select(AuditEvent).where(AuditEvent.id == event.id)
            )
            saved = result.scalar_one()
            assert saved.ip_address is None

    run_async(_run())


def test_audit_events_table_exists(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:

            def _inspect(sync_conn):
                inspector = inspect(sync_conn)
                audit_columns = inspector.get_columns("audit_events")
                columns = {column["name"] for column in audit_columns}
                return inspector.has_table("audit_events"), columns

            exists = await session.connection()
            has_table, columns = await exists.run_sync(_inspect)
            assert has_table is True
            assert "legal_hold_until" in columns

    run_async(_run())


@pytest.mark.parametrize(
    "metadata",
    [
        {"token_hash": "x"},
        {"level1": {"level2": {"level3": {"level4": "deep"}}}},
        {"payload": "x" * 9000},
    ],
)
def test_metadata_validation_rejects_invalid(
    migrated_session_factory, metadata
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            with pytest.raises(ValueError):
                await AuditEventService(session).record_event(
                    audit_context=AuditContext(actor_user_id=None),
                    category=AuditCategory.TENANT,
                    action=AuditAction.INVITE_REVOKED,
                    target_type=AuditTargetType.INVITE,
                    target_id=None,
                    metadata_json=metadata,
                )

    run_async(_run())


def test_audit_retention_anonymises_expired_identifiers(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        now = datetime(2026, 5, 21, tzinfo=UTC)
        async with migrated_session_factory() as session:
            actor = User(
                external_auth_id=f"auth-{uuid4()}",
                email="actor@example.com",
                email_verified=True,
            )
            session.add(actor)
            await session.flush()

            old_event = AuditEvent(
                actor_user_id=actor.id,
                category=AuditCategory.TENANT.value,
                action=AuditAction.ORGANISATION_UPDATED.value,
                target_type=AuditTargetType.ORGANISATION.value,
                target_id=uuid4(),
                reason="legacy support note",
                metadata_json={"changed_fields": ["slug"]},
                ip_address="hmac:v1:legacyidentifier",
                user_agent="browser:chrome",
                created_at=now - timedelta(days=366),
            )
            recent_event = AuditEvent(
                actor_user_id=actor.id,
                category=AuditCategory.TENANT.value,
                action=AuditAction.ORGANISATION_UPDATED.value,
                target_type=AuditTargetType.ORGANISATION.value,
                target_id=uuid4(),
                ip_address="hmac:v1:recentidentifier",
                created_at=now - timedelta(days=30),
            )
            session.add_all([old_event, recent_event])
            await session.flush()

            count = await AuditEventService(session).anonymise_expired_events(
                settings=AuditSettings(retention_days=365),
                now=now,
            )
            await session.commit()
            await session.refresh(old_event)
            await session.refresh(recent_event)

            assert count == 1
            saved_old = old_event
            saved_recent = recent_event
            assert saved_old.actor_user_id is None
            assert saved_old.reason is None
            assert saved_old.metadata_json is None
            assert saved_old.ip_address is None
            assert saved_old.user_agent is None
            assert saved_old.category == AuditCategory.TENANT.value
            assert saved_old.action == AuditAction.ORGANISATION_UPDATED.value
            assert saved_recent.ip_address == "hmac:v1:recentidentifier"

    run_async(_run())


def test_audit_retention_respects_legal_hold(migrated_session_factory) -> None:
    async def _run() -> None:
        now = datetime(2026, 5, 21, tzinfo=UTC)
        async with migrated_session_factory() as session:
            held_event = AuditEvent(
                actor_user_id=None,
                category=AuditCategory.SECURITY.value,
                action=AuditAction.USER_SUSPENDED.value,
                target_type=AuditTargetType.USER.value,
                target_id=uuid4(),
                reason="held security investigation",
                ip_address="hmac:v1:heldidentifier",
                user_agent="browser:firefox",
                legal_hold_until=now + timedelta(days=30),
                created_at=now - timedelta(days=731),
            )
            session.add(held_event)
            await session.flush()

            count = await AuditEventService(session).anonymise_expired_events(
                settings=AuditSettings(security_retention_days=730),
                now=now,
            )
            await session.commit()
            await session.refresh(held_event)

            assert count == 0
            saved_event = held_event
            assert saved_event.reason == "held security investigation"
            assert saved_event.ip_address == "hmac:v1:heldidentifier"
            assert saved_event.user_agent == "browser:firefox"

    run_async(_run())


def test_actor_mismatch_is_rejected_in_invite_service(migrated_session_factory) -> None:
    from app.invites.services.invites import InviteService

    async def _run() -> None:
        async with migrated_session_factory() as session:
            service = InviteService(session)
            with pytest.raises(
                ValueError, match="Audit actor does not match action actor"
            ):
                await service.revoke_invite(
                    organisation_id=uuid4(),
                    invite_id=uuid4(),
                    actor_user_id=uuid4(),
                    audit_context=AuditContext(actor_user_id=uuid4()),
                )

    run_async(_run())

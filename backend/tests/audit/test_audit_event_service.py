from __future__ import annotations

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
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.security]


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


def test_build_audit_context_uses_client_host_and_ignores_xff() -> None:
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
                return inspect(sync_conn).has_table("audit_events")

            exists = await session.connection()
            has_table = await exists.run_sync(_inspect)
            assert has_table is True

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

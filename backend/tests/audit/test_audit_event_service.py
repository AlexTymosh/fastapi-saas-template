from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import inspect, select
from starlette.requests import Request

from app.audit.context import AuditContext, build_audit_context_from_request
from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.audit.services.audit_events import AuditEventService
from tests.helpers.asyncio_runner import run_async


def test_audit_service_persists_event(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = await AuditEventService(session).record_event(
                audit_context=AuditContext(
                    actor_user_id=None, ip_address="127.0.0.1", user_agent="pytest"
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
            assert event.ip_address == "127.0.0.1"

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


def test_user_agent_is_truncated_to_512(migrated_session_factory) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = await AuditEventService(session).record_event(
                audit_context=AuditContext(
                    actor_user_id=None,
                    ip_address="127.0.0.1",
                    user_agent="x" * 600,
                ),
                category=AuditCategory.TENANT,
                action=AuditAction.ORGANISATION_UPDATED,
                target_type=AuditTargetType.ORGANISATION,
                target_id=uuid4(),
            )
            await session.commit()
            assert event.user_agent is not None
            assert len(event.user_agent) == 512

    run_async(_run())


def test_ip_address_too_long_raises_and_event_not_written(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            with pytest.raises(ValueError, match="Audit IP address exceeds max length"):
                await AuditEventService(session).record_event(
                    audit_context=AuditContext(
                        actor_user_id=None,
                        ip_address="x" * 46,
                    ),
                    category=AuditCategory.TENANT,
                    action=AuditAction.ORGANISATION_UPDATED,
                    target_type=AuditTargetType.ORGANISATION,
                    target_id=uuid4(),
                )
            await session.rollback()
            result = await session.execute(select(AuditEvent))
            assert list(result.scalars().all()) == []

    run_async(_run())


def test_build_audit_context_from_request_uses_client_host_and_ignores_xff() -> None:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/v1/health/live",
        "headers": [
            (b"user-agent", b"pytest-agent"),
            (b"x-forwarded-for", b"203.0.113.1"),
        ],
        "client": ("127.0.0.1", 1234),
    }

    async def _receive() -> dict[str, object]:
        return {"type": "http.request", "body": b"", "more_body": False}

    request = Request(scope, receive=_receive)
    context = build_audit_context_from_request(
        actor_user_id=uuid4(),
        request=request,
    )
    assert context.ip_address == "127.0.0.1"
    assert context.user_agent == "pytest-agent"

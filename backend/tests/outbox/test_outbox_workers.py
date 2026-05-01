from __future__ import annotations

import asyncio
from uuid import UUID

from app.outbox.dispatcher import (
    claim_and_enqueue_due_outbox_events,
    run_dispatcher_loop,
)
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import _process_outbox_event
from tests.api.test_invites import InMemoryInviteTokenSink, _drain_outbox, _identity_for
from tests.helpers.asyncio_runner import run_async


def test_claim_due_events_marks_pending_events_processing(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.INVITE_CREATED.value,
                    payload_json={"invite_id": "1", "raw_token": "a"},
                    aggregate_type="invite",
                    aggregate_id=UUID("00000000-0000-0000-0000-000000000121"),
                    status=OutboxStatus.PENDING.value,
                )
            )
            await session.commit()

        async with migrated_session_factory() as session:
            async with session.begin():
                claimed = await OutboxEventRepository(session).claim_due_events(
                    limit=10
                )
                assert len(claimed) == 1
                assert claimed[0].status == OutboxStatus.PROCESSING.value
                assert claimed[0].locked_at is not None

    run_async(_run())


def test_claim_and_enqueue_due_outbox_events_enqueues_claimed_events(
    migrated_session_factory, monkeypatch
) -> None:
    sent_event_ids: list[str] = []
    monkeypatch.setattr(
        "app.outbox.dispatcher.process_outbox_event.send",
        lambda event_id: sent_event_ids.append(event_id),
    )
    monkeypatch.setattr(
        "app.outbox.dispatcher.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.INVITE_CREATED.value,
                    payload_json={"invite_id": "1", "raw_token": "a"},
                    aggregate_type="invite",
                    aggregate_id=UUID("00000000-0000-0000-0000-000000000131"),
                    status=OutboxStatus.PENDING.value,
                )
            )
            await session.commit()
        count = await claim_and_enqueue_due_outbox_events(limit=10)
        assert count == 1
        assert len(sent_event_ids) == 1

    run_async(_run())


def test_dispatcher_loop_runs_until_cancelled(monkeypatch) -> None:
    called = {"ticks": 0}

    async def _fake_claim(limit: int = 100) -> int:
        called["ticks"] += 1
        return 0

    monkeypatch.setattr(
        "app.outbox.dispatcher.claim_and_enqueue_due_outbox_events", _fake_claim
    )

    async def _run() -> None:
        task = asyncio.create_task(run_dispatcher_loop(interval=0, batch_size=1))
        await asyncio.sleep(0)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    run_async(_run())
    assert called["ticks"] >= 1


def test_worker_noops_when_event_is_not_processing(
    migrated_session_factory, monkeypatch
) -> None:
    sink = InMemoryInviteTokenSink()
    monkeypatch.setattr("app.outbox.workers.get_invite_token_sink", lambda: sink)
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000111"),
                payload_json={
                    "invite_id": "00000000-0000-0000-0000-000000000111",
                    "raw_token": "secret-token",
                },
                status=OutboxStatus.PENDING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)
        await _process_outbox_event(event_id)
        assert sink.deliveries == []

    run_async(_run())


def test_process_outbox_event_marks_processed_on_success(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    sink = InMemoryInviteTokenSink()
    monkeypatch.setattr("app.outbox.workers.get_invite_token_sink", lambda: sink)
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    owner = authenticated_client_factory(
        identity=_identity_for("kc-owner-outbox", "owner-outbox@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with owner.client as client:
        org = client.post(
            "/api/v1/organisations", json={"name": "Org", "slug": "org-outbox"}
        )
        invite = client.post(
            f"/api/v1/organisations/{org.json()['id']}/invites",
            json={"email": "worker@example.com", "role": "member"},
        )
        assert invite.status_code == 201

    _drain_outbox(migrated_session_factory, monkeypatch)

    async def _assert_processed() -> None:
        async with migrated_session_factory() as session:
            processed = await OutboxEventRepository(session).list_pending_due_events(
                limit=10
            )
            assert processed == []

    run_async(_assert_processed())
    assert sink.token_for_email("worker@example.com")


def test_process_outbox_event_failure_commits_attempts(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _assert_failure() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000111"),
                payload_json={
                    "invite_id": "00000000-0000-0000-0000-000000000111",
                    "raw_token": "secret-token",
                },
                max_attempts=1,
                status=OutboxStatus.PROCESSING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        await _process_outbox_event(event_id)

        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved is not None
            assert saved.status == OutboxStatus.FAILED.value
            assert saved.attempts == 1
            assert saved.last_error == "invite_not_found"

    run_async(_assert_failure())

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.outbox.dispatcher import claim_and_enqueue_due_outbox_events
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import process_outbox_event
from tests.api.test_invites import InMemoryInviteTokenSink, _identity_for
from tests.helpers.asyncio_runner import run_async


def test_claim_due_events_marks_pending_events_processing(
    migrated_session_factory,
) -> None:
    async def _check() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000121"),
            )
            session.add(event)
            await session.commit()

        async with migrated_session_factory() as session:
            async with session.begin():
                claimed = await OutboxEventRepository(session).claim_due_events(
                    limit=10
                )
                assert len(claimed) == 1
                assert claimed[0].status == OutboxStatus.PROCESSING.value

    run_async(_check())


def test_worker_processes_claimed_invite_created_event(
    authenticated_client_factory,
    migrated_database_url,
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

    async def _process_all() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                claimed = await OutboxEventRepository(session).claim_due_events(
                    limit=10
                )
        for event in claimed:
            await process_outbox_event.fn(str(event.id))

    run_async(_process_all())
    assert sink.token_for_email("worker@example.com")


def test_dispatcher_enqueues_claimed_events(
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

    async def _check() -> None:
        async with migrated_session_factory() as session:
            due_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000131"),
                status=OutboxStatus.PENDING.value,
            )
            future_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "2", "raw_token": "b"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000132"),
                status=OutboxStatus.PENDING.value,
                next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            session.add_all([due_event, future_event])
            await session.commit()
            due_event_id = str(due_event.id)

        count = await claim_and_enqueue_due_outbox_events(limit=10)
        assert count == 1
        assert sent_event_ids == [due_event_id]

    run_async(_check())

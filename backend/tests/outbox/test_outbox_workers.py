from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import _process_outbox_event, enqueue_pending_outbox_events
from tests.api.test_invites import InMemoryInviteTokenSink, _drain_outbox, _identity_for
from tests.helpers.asyncio_runner import run_async


def test_process_outbox_event_marks_processed_on_success(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
    monkeypatch,
) -> None:
    sink = InMemoryInviteTokenSink()
    monkeypatch.setattr("app.outbox.workers.get_invite_token_sink", lambda: sink)

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
    migrated_session_factory,
) -> None:
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


def test_enqueue_pending_outbox_events_sends_only_due_pending(
    migrated_session_factory, monkeypatch
) -> None:
    sent_event_ids: list[str] = []
    monkeypatch.setattr(
        "app.outbox.workers.process_outbox_event.send",
        lambda event_id: sent_event_ids.append(event_id),
    )

    async def _assert_enqueue() -> None:
        async with migrated_session_factory() as session:
            due_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000121"),
                status=OutboxStatus.PENDING.value,
            )
            future_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "2", "raw_token": "b"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000122"),
                status=OutboxStatus.PENDING.value,
                next_attempt_at=datetime.now(UTC) + timedelta(minutes=5),
            )
            session.add_all([due_event, future_event])
            await session.commit()
            due_event_id = str(due_event.id)

        await enqueue_pending_outbox_events.fn(limit=10)
        assert sent_event_ids == [due_event_id]

    run_async(_assert_enqueue())

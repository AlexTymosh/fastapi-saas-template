from __future__ import annotations

import asyncio
from hashlib import sha256
from uuid import UUID

import pytest
from cryptography.fernet import Fernet

from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.outbox.dispatcher import (
    claim_and_enqueue_due_outbox_events,
    run_dispatcher_loop,
)
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.workers import _process_outbox_event
from tests.api.test_invites import InMemoryInviteTokenSink, _drain_outbox, _identity_for
from tests.helpers.asyncio_runner import run_async
from tests.helpers.outbox import process_all_claimed_outbox_events
from tests.helpers.settings import reset_settings_cache


def test_claim_due_events_marks_pending_events_processing(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            session.add(
                OutboxEvent(
                    event_type=OutboxEventType.INVITE_CREATED.value,
                    payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
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


def test_drain_helper_claims_then_processes(
    migrated_session_factory, monkeypatch
) -> None:
    claimed_ids: list[str] = []

    async def _fake_process(event_id: str) -> None:
        claimed_ids.append(event_id)

    monkeypatch.setattr("tests.helpers.outbox._process_outbox_event", _fake_process)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000141"),
                status=OutboxStatus.PENDING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        await process_all_claimed_outbox_events(migrated_session_factory)
        assert claimed_ids == [event_id]

    run_async(_run())


def test_pending_events_are_not_processed_directly(
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
                    "encrypted_raw_token": "secret-token",
                },
                status=OutboxStatus.PENDING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        await _process_outbox_event(event_id)
        assert sink._tokens_by_email == {}

    run_async(_run())


def test_claimed_processing_events_are_delivered(
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
                    payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
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


def test_dispatcher_releases_event_when_enqueue_fails(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.dispatcher.process_outbox_event.send",
        lambda event_id: (_ for _ in ()).throw(RuntimeError("enqueue down")),
    )
    monkeypatch.setattr(
        "app.outbox.dispatcher.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000133"),
                status=OutboxStatus.PENDING.value,
            )
            session.add(event)
            await session.commit()
            event_id = event.id
        count = await claim_and_enqueue_due_outbox_events(limit=10)
        assert count == 0
        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(event_id)
            assert saved is not None
            assert saved.status != OutboxStatus.PROCESSING.value
            assert saved.locked_at is None
            assert saved.last_error is not None
            assert "enqueue_failed:RuntimeError" in saved.last_error

    run_async(_run())


def test_dispatcher_loop_runs_until_cancelled(monkeypatch) -> None:
    called = {"ticks": 0}

    async def _fake_recover() -> int:
        return 0

    async def _fake_claim(limit: int = 100) -> int:
        called["ticks"] += 1
        return 0

    monkeypatch.setattr(
        "app.outbox.dispatcher.recover_stale_processing_events",
        _fake_recover,
    )
    monkeypatch.setattr(
        "app.outbox.dispatcher.claim_and_enqueue_due_outbox_events",
        _fake_claim,
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
                    "encrypted_raw_token": "secret-token",
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


def test_worker_runtime_fails_without_redis(monkeypatch) -> None:
    import importlib

    tasks_broker_module = importlib.import_module("app.core.tasks.broker")

    monkeypatch.setattr(
        tasks_broker_module,
        "get_settings",
        lambda: type("S", (), {"redis": type("R", (), {"url": None})()})(),
    )
    monkeypatch.setattr(tasks_broker_module, "_configured_broker", None)
    monkeypatch.setattr(tasks_broker_module, "broker", None)

    with pytest.raises(RuntimeError, match="REDIS__URL"):
        tasks_broker_module.configure_broker(require_redis=True)


def test_process_outbox_event_marks_decryption_failure_with_wrong_key(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )
    monkeypatch.setenv(
        "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )
    reset_settings_cache()

    async def _run() -> None:
        from app.outbox.services.payload_crypto import OutboxPayloadCrypto

        crypto = OutboxPayloadCrypto(Fernet.generate_key().decode("utf-8"))
        encrypted = crypto.encrypt_token("super-secret-token")
        invite_id = UUID("00000000-0000-0000-0000-000000000111")
        async with migrated_session_factory() as session:
            session.add(
                Invite(
                    id=invite_id,
                    email="decrypt-failure@example.com",
                    organisation_id=UUID("00000000-0000-0000-0000-000000000001"),
                    role=MembershipRole.MEMBER,
                    status=InviteStatus.PENDING,
                    token_hash=sha256(b"super-secret-token").hexdigest(),
                )
            )
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000211"),
                payload_json={
                    "invite_id": str(invite_id),
                    "encrypted_raw_token": encrypted,
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
            assert saved.last_error == "outbox_payload_decryption_failed"

    run_async(_run())


def test_recover_stale_processing_events_requeues_old_processing_event(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000151"),
                status=OutboxStatus.PROCESSING.value,
            )
            session.add(event)
            await session.commit()
            event_id = event.id
        async with migrated_session_factory() as session:
            async with session.begin():
                repo = OutboxEventRepository(session)
                claimed = await repo.get_by_id(event_id)
                assert claimed is not None
                from datetime import UTC, datetime, timedelta

                claimed.locked_at = datetime.now(UTC) - timedelta(seconds=1000)
                await session.flush()
        async with migrated_session_factory() as session:
            async with session.begin():
                recovered = await OutboxEventRepository(
                    session
                ).recover_stale_processing_events(stale_timeout_seconds=300, limit=10)
                assert len(recovered) == 1
        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(event_id)
            assert saved is not None
            assert saved.status != OutboxStatus.PROCESSING.value
            assert saved.locked_at is None
            assert saved.last_error == "stale_processing_recovered"
            assert saved.attempts == 1

    run_async(_run())


def test_recover_stale_processing_events_ignores_fresh_processing_event(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                payload_json={"invite_id": "1", "encrypted_raw_token": "a"},
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000152"),
                status=OutboxStatus.PROCESSING.value,
            )
            session.add(event)
            await session.commit()
            event_id = event.id
        async with migrated_session_factory() as session:
            async with session.begin():
                recovered = await OutboxEventRepository(
                    session
                ).recover_stale_processing_events(stale_timeout_seconds=300, limit=10)
                assert recovered == []
        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(event_id)
            assert saved is not None
            assert saved.status == OutboxStatus.PROCESSING.value

    run_async(_run())


def test_worker_marks_invalid_payload_failed_attempt(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000171"),
                payload_json={"encrypted_raw_token": "x"},
                status=OutboxStatus.PROCESSING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)
        await _process_outbox_event(event_id)
        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved is not None
            assert saved.status != OutboxStatus.PROCESSING.value
            assert saved.attempts == 1
            assert saved.last_error == "malformed_outbox_payload"

    run_async(_run())


def test_worker_marks_invalid_invite_id_payload_failed_attempt(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000172"),
                payload_json={
                    "invite_id": "not-a-uuid",
                    "encrypted_raw_token": "x",
                },
                status=OutboxStatus.PROCESSING.value,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)
        await _process_outbox_event(event_id)
        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved is not None
            assert saved.status != OutboxStatus.PROCESSING.value
            assert saved.attempts == 1
            assert saved.last_error == "malformed_outbox_payload"

    run_async(_run())


def test_worker_marks_missing_encrypted_token_payload_failed_attempt(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        invite_id = UUID("00000000-0000-0000-0000-000000000173")
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000173"),
                payload_json={"invite_id": str(invite_id)},
                status=OutboxStatus.PROCESSING.value,
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
            assert saved.last_error == "malformed_outbox_payload"

    run_async(_run())


def test_worker_marks_empty_encrypted_token_payload_failed_attempt(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        invite_id = UUID("00000000-0000-0000-0000-000000000174")
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000174"),
                payload_json={
                    "invite_id": str(invite_id),
                    "encrypted_raw_token": "   ",
                },
                status=OutboxStatus.PROCESSING.value,
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
            assert saved.last_error == "malformed_outbox_payload"

    run_async(_run())


def test_worker_malformed_payload_does_not_call_sink(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    class _MustNotCallSink:
        async def deliver(self, invite, raw_token):  # type: ignore[no-untyped-def]
            raise AssertionError("sink must not be called for malformed payload")

    monkeypatch.setattr(
        "app.outbox.workers.get_invite_token_sink", lambda: _MustNotCallSink()
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000175"),
                payload_json={"encrypted_raw_token": "x"},
                status=OutboxStatus.PROCESSING.value,
                max_attempts=1,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)
        await _process_outbox_event(event_id)

    run_async(_run())


def test_worker_malformed_payload_retries_as_pending(
    migrated_session_factory, monkeypatch
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000176"),
                payload_json={"encrypted_raw_token": "x"},
                status=OutboxStatus.PROCESSING.value,
                max_attempts=2,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)
        await _process_outbox_event(event_id)
        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved is not None
            assert saved.status == OutboxStatus.PENDING.value
            assert saved.attempts == 1
            assert saved.last_error == "malformed_outbox_payload"
            assert saved.next_attempt_at is not None

    run_async(_run())


def test_worker_malformed_payload_does_not_leak_sensitive_token(
    migrated_session_factory, monkeypatch, caplog
) -> None:
    monkeypatch.setattr(
        "app.outbox.workers.get_session_factory", lambda: migrated_session_factory
    )

    async def _run() -> None:
        async with migrated_session_factory() as session:
            event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=UUID("00000000-0000-0000-0000-000000000177"),
                payload_json={
                    "invite_id": "not-a-uuid",
                    "encrypted_raw_token": "SECRET_SHOULD_NOT_LEAK",
                },
                status=OutboxStatus.PROCESSING.value,
                max_attempts=1,
            )
            session.add(event)
            await session.commit()
            event_id = str(event.id)

        await _process_outbox_event(event_id)

        async with migrated_session_factory() as session:
            saved = await OutboxEventRepository(session).get_by_id(UUID(event_id))
            assert saved is not None
            assert "SECRET_SHOULD_NOT_LEAK" not in (saved.last_error or "")

    run_async(_run())
    assert "SECRET_SHOULD_NOT_LEAK" not in caplog.text

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import update

from app.audit.context import AuditContext
from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.core.config.settings import get_settings
from app.invites.anonymisation import (
    SCRUBBED_INVITE_EMAIL_DOMAIN,
    SCRUBBED_INVITE_TOKEN_PREFIX,
    scrubbed_invite_email,
    scrubbed_invite_token_hash,
)
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.privacy import maintenance as privacy_maintenance
from app.privacy.maintenance import (
    expire_ready_export_artifacts,
    run_privacy_retention_maintenance,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStatus
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


@pytest.fixture(autouse=True)
def isolated_export_storage(monkeypatch, tmp_path):
    storage_path = tmp_path / "privacy-exports"
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield storage_path
    finally:
        get_settings.cache_clear()


async def _create_approved_export_dsr(session):
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    dsr = DataSubjectRequest(
        request_type="export",
        status=DataSubjectRequestStatus.APPROVED.value,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=datetime.now(UTC),
        due_at=datetime.now(UTC),
    )
    session.add(dsr)
    await session.flush()
    return user, dsr


async def _create_expired_ready_artifact(session):
    user, dsr = await _create_approved_export_dsr(session)
    service = ExportArtifactService(session)
    artifact = await service.request_export_artifact(
        request_id=dsr.id,
        requested_by_user_id=user.id,
        audit_context=AuditContext(actor_user_id=user.id),
    )
    expired_at = datetime.now(UTC) - timedelta(seconds=1)
    storage_key = f"exports/{artifact.id}/artifact.zip"
    artifact.status = ExportArtifactStatus.READY.value
    artifact.storage_key = storage_key
    artifact.filename = "artifact.zip"
    artifact.content_type = "application/zip"
    artifact.size_bytes = 7
    artifact.checksum_sha256 = "0" * 64
    artifact.completed_at = expired_at - timedelta(minutes=1)
    artifact.expires_at = expired_at
    await service.repo.save(artifact)
    service.storage.put_bytes(storage_key, b"payload", "application/zip")
    dsr.execution_status = DataSubjectRequestExecutionStatus.READY.value
    dsr.execution_completed_at = artifact.completed_at
    await service.dsr_repo.save(dsr)
    return artifact.id, storage_key, dsr.id


async def _create_retention_subject(session, *, old: datetime):
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"retention-{uuid4()}@example.com",
        email_verified=True,
    )
    organisation = Organisation(
        name="Retention Test Org",
        slug=f"retention-{uuid4()}",
        created_at=old,
        updated_at=old,
    )
    session.add_all([user, organisation])
    await session.flush()
    return user, organisation


async def _create_retained_privacy_rows(session):
    now = datetime.now(UTC)
    old = now - timedelta(days=get_settings().audit.retention_days + 1)
    user, organisation = await _create_retention_subject(session, old=old)

    invite = Invite(
        email=user.email,
        organisation_id=organisation.id,
        role=MembershipRole.MEMBER,
        status=InviteStatus.ACCEPTED,
        token_hash=f"token-{uuid4()}",
        expires_at=old,
        revoked_by_user_id=user.id,
        created_at=old,
        updated_at=old,
    )
    session.add(invite)
    await session.flush()

    outbox_event = OutboxEvent(
        event_type=OutboxEventType.INVITE_CREATED.value,
        aggregate_type="invite",
        aggregate_id=invite.id,
        payload_json={
            "email": user.email,
            "encrypted_raw_token": "ciphertext",
            "invite_id": str(invite.id),
            "organisation_id": str(organisation.id),
            "role": MembershipRole.MEMBER.value,
        },
        status=OutboxStatus.FAILED.value,
        attempts=1,
        max_attempts=1,
        processed_at=old,
        last_error=f"delivery failed for {user.email}",
        created_at=old,
        updated_at=old,
    )
    audit_event = AuditEvent(
        actor_user_id=user.id,
        category=AuditCategory.TENANT.value,
        action=AuditAction.INVITE_CREATED.value,
        target_type=AuditTargetType.USER.value,
        target_id=user.id,
        reason=f"manual action for {user.email}",
        metadata_json={"email": user.email},
        ip_address="192.0.2.10",
        user_agent="Browser/1.0",
        created_at=old,
    )
    dsr = DataSubjectRequest(
        request_type="access",
        status=DataSubjectRequestStatus.SUBMITTED.value,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=old,
        due_at=old + timedelta(days=30),
        idempotency_key_hash="hash",
        idempotency_fingerprint="fingerprint",
        idempotency_key_expires_at=old,
        created_at=old,
        updated_at=old,
    )
    session.add_all([outbox_event, audit_event, dsr])
    await session.flush()
    return {
        "user_id": user.id,
        "organisation_id": organisation.id,
        "invite_id": invite.id,
        "outbox_event_id": outbox_event.id,
        "audit_event_id": audit_event.id,
        "dsr_id": dsr.id,
    }


def test_privacy_retention_dry_run_does_not_mutate_or_delete_storage(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            artifact_id, storage_key, dsr_id = await _create_expired_ready_artifact(
                session
            )
            service = ExportArtifactService(session)

            count = await expire_ready_export_artifacts(session, dry_run=True)

            assert count == 1
            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.READY.value
            assert persisted_artifact.storage_key == storage_key
            assert service.storage.exists(storage_key) is True
            persisted_dsr = await service.dsr_repo.get_by_id(dsr_id)
            assert persisted_dsr is not None
            assert (
                persisted_dsr.execution_status
                == DataSubjectRequestExecutionStatus.READY.value
            )

    run_async(_run())


def test_privacy_retention_expires_before_purging_storage_object(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            artifact_id, storage_key, dsr_id = await _create_expired_ready_artifact(
                session
            )
            await session.commit()
            service = ExportArtifactService(session)

            count = await expire_ready_export_artifacts(session)

            assert count == 1
            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.EXPIRED.value
            assert persisted_artifact.storage_key == storage_key
            assert persisted_artifact.filename == "artifact.zip"
            assert persisted_artifact.content_type == "application/zip"
            assert persisted_artifact.size_bytes == 7
            assert persisted_artifact.checksum_sha256 == "0" * 64
            assert service.storage.exists(storage_key) is True
            persisted_dsr = await service.dsr_repo.get_by_id(dsr_id)
            assert persisted_dsr is not None
            assert (
                persisted_dsr.execution_status
                == DataSubjectRequestExecutionStatus.FAILED.value
            )
            assert persisted_dsr.execution_failure_reason_code == "artifact_expired"

            await session.commit()
            count = await expire_ready_export_artifacts(session)

            assert count == 1
            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.EXPIRED.value
            assert persisted_artifact.storage_key is None
            assert persisted_artifact.filename is None
            assert persisted_artifact.content_type is None
            assert persisted_artifact.size_bytes is None
            assert persisted_artifact.checksum_sha256 is None
            assert service.storage.exists(storage_key) is False

    run_async(_run())


def test_privacy_retention_rollback_keeps_ready_artifact_storage_valid(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            artifact_id, storage_key, dsr_id = await _create_expired_ready_artifact(
                session
            )
            await session.commit()
            service = ExportArtifactService(session)

            count = await expire_ready_export_artifacts(session)
            assert count == 1
            await session.rollback()
            session.expire_all()

            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.READY.value
            assert persisted_artifact.storage_key == storage_key
            assert service.storage.exists(storage_key) is True
            persisted_dsr = await service.dsr_repo.get_by_id(dsr_id)
            assert persisted_dsr is not None
            assert (
                persisted_dsr.execution_status
                == DataSubjectRequestExecutionStatus.READY.value
            )

    run_async(_run())


def test_privacy_retention_summary_dry_run_covers_non_export_tables(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            ids = await _create_retained_privacy_rows(session)

            summary = await run_privacy_retention_maintenance(
                session,
                dry_run=True,
            )

            assert summary.expired_export_artifacts == 0
            assert summary.anonymised_invites == 1
            assert summary.scrubbed_outbox_events == 1
            assert summary.minimised_audit_events == 1
            assert summary.cleaned_dsr_idempotency_keys == 1
            assert summary.total == 4

            invite = await session.get(Invite, ids["invite_id"])
            assert invite is not None
            assert not invite.email.endswith(f"@{SCRUBBED_INVITE_EMAIL_DOMAIN}")
            outbox_event = await session.get(OutboxEvent, ids["outbox_event_id"])
            assert outbox_event is not None
            assert "email" in outbox_event.payload_json
            audit_event = await session.get(AuditEvent, ids["audit_event_id"])
            assert audit_event is not None
            assert audit_event.actor_user_id is not None
            dsr = await session.get(DataSubjectRequest, ids["dsr_id"])
            assert dsr is not None
            assert dsr.idempotency_key_hash == "hash"

    run_async(_run())


def test_privacy_retention_runner_minimises_non_export_tables(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            ids = await _create_retained_privacy_rows(session)

            summary = await run_privacy_retention_maintenance(session)

            assert summary.as_log_extra()["total"] == 4
            invite = await session.get(Invite, ids["invite_id"])
            assert invite is not None
            assert invite.email.endswith(f"@{SCRUBBED_INVITE_EMAIL_DOMAIN}")
            assert invite.token_hash.startswith(f"{SCRUBBED_INVITE_TOKEN_PREFIX}:")
            assert invite.expires_at is None
            assert invite.revoked_by_user_id is None

            outbox_event = await session.get(OutboxEvent, ids["outbox_event_id"])
            assert outbox_event is not None
            assert outbox_event.payload_json == {
                "invite_id": str(ids["invite_id"]),
                "organisation_id": str(ids["organisation_id"]),
                "role": MembershipRole.MEMBER.value,
                "sensitive_payload_scrubbed": True,
                "privacy_retention_scrubbed": True,
            }
            assert outbox_event.last_error == "privacy_retention_scrubbed"

            audit_event = await session.get(AuditEvent, ids["audit_event_id"])
            assert audit_event is not None
            assert audit_event.actor_user_id is None
            assert audit_event.target_id == ids["user_id"]
            assert audit_event.reason is None
            assert audit_event.metadata_json is None
            assert audit_event.ip_address is None
            assert audit_event.user_agent is None

            dsr = await session.get(DataSubjectRequest, ids["dsr_id"])
            assert dsr is not None
            assert dsr.idempotency_key_hash is None
            assert dsr.idempotency_fingerprint is None
            assert dsr.idempotency_key_expires_at is None

    run_async(_run())


def test_privacy_retention_invite_batch_skips_already_scrubbed_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            invite_retention_days = get_settings().invite_retention.accepted_days
            old = now - timedelta(days=invite_retention_days + 2)
            older = old - timedelta(days=1)
            user, organisation = await _create_retention_subject(session, old=older)

            scrubbed_invite_id = uuid4()
            target_invite_id = uuid4()
            session.add_all(
                [
                    Invite(
                        id=scrubbed_invite_id,
                        email=scrubbed_invite_email(scrubbed_invite_id),
                        organisation_id=organisation.id,
                        role=MembershipRole.MEMBER,
                        status=InviteStatus.ACCEPTED,
                        token_hash=scrubbed_invite_token_hash(scrubbed_invite_id),
                        expires_at=None,
                        revoked_by_user_id=None,
                        created_at=older,
                        updated_at=older,
                    ),
                    Invite(
                        id=target_invite_id,
                        email=user.email,
                        organisation_id=organisation.id,
                        role=MembershipRole.MEMBER,
                        status=InviteStatus.ACCEPTED,
                        token_hash=f"token-{uuid4()}",
                        expires_at=old,
                        revoked_by_user_id=user.id,
                        created_at=old,
                        updated_at=old,
                    ),
                ]
            )
            await session.flush()

            summary = await run_privacy_retention_maintenance(
                session,
                now=now,
                limit=1,
            )

            assert summary.anonymised_invites == 1
            target_invite = await session.get(Invite, target_invite_id)
            assert target_invite is not None
            assert target_invite.email == scrubbed_invite_email(target_invite_id)
            assert target_invite.token_hash == scrubbed_invite_token_hash(
                target_invite_id
            )
            assert target_invite.expires_at is None
            assert target_invite.revoked_by_user_id is None

    run_async(_run())


def test_privacy_retention_outbox_batch_skips_already_scrubbed_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(days=31)
            older = old - timedelta(days=1)
            scrubbed_event_id = uuid4()
            target_event_id = uuid4()
            target_invite_id = uuid4()
            organisation_id = uuid4()

            session.add_all(
                [
                    OutboxEvent(
                        id=scrubbed_event_id,
                        event_type=OutboxEventType.INVITE_CREATED.value,
                        aggregate_type="invite",
                        aggregate_id=uuid4(),
                        payload_json={"privacy_retention_scrubbed": True},
                        status=OutboxStatus.PROCESSED.value,
                        processed_at=older,
                        created_at=older,
                        updated_at=older,
                    ),
                    OutboxEvent(
                        id=target_event_id,
                        event_type=OutboxEventType.INVITE_CREATED.value,
                        aggregate_type="invite",
                        aggregate_id=target_invite_id,
                        payload_json={
                            "email": "retention@example.com",
                            "encrypted_raw_token": "ciphertext",
                            "invite_id": str(target_invite_id),
                            "organisation_id": str(organisation_id),
                            "role": MembershipRole.MEMBER.value,
                        },
                        status=OutboxStatus.FAILED.value,
                        attempts=1,
                        max_attempts=1,
                        processed_at=old,
                        last_error="delivery failed for retention@example.com",
                        created_at=old,
                        updated_at=old,
                    ),
                ]
            )
            await session.flush()

            summary = await run_privacy_retention_maintenance(
                session,
                now=now,
                limit=1,
            )

            assert summary.scrubbed_outbox_events == 1
            target_event = await session.get(OutboxEvent, target_event_id)
            assert target_event is not None
            assert target_event.payload_json == {
                "invite_id": str(target_invite_id),
                "organisation_id": str(organisation_id),
                "role": MembershipRole.MEMBER.value,
                "sensitive_payload_scrubbed": True,
                "privacy_retention_scrubbed": True,
            }
            assert target_event.last_error == "privacy_retention_scrubbed"

    run_async(_run())


def test_privacy_retention_audit_update_rechecks_legal_hold(
    monkeypatch,
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(days=get_settings().audit.retention_days + 1)
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-retention-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(user)
            await session.flush()

            audit_event = AuditEvent(
                actor_user_id=user.id,
                category=AuditCategory.TENANT.value,
                action=AuditAction.USER_SUSPENDED.value,
                target_type=AuditTargetType.USER.value,
                target_id=user.id,
                reason="manual review",
                metadata_json={"case": "retention"},
                ip_address="192.0.2.20",
                user_agent="Browser/2.0",
                created_at=old,
            )
            session.add(audit_event)
            await session.flush()

            original_selector = privacy_maintenance._retained_audit_event_ids

            async def _select_then_place_legal_hold(
                session,
                *,
                now: datetime,
                limit: int,
            ):
                ids = await original_selector(session, now=now, limit=limit)
                await session.execute(
                    update(AuditEvent)
                    .where(AuditEvent.id.in_(ids))
                    .values(legal_hold_until=now + timedelta(days=1))
                    .execution_options(synchronize_session=False)
                )
                return ids

            monkeypatch.setattr(
                privacy_maintenance,
                "_retained_audit_event_ids",
                _select_then_place_legal_hold,
            )

            summary = await privacy_maintenance.run_privacy_retention_maintenance(
                session,
                now=now,
            )

            assert summary.minimised_audit_events == 0
            await session.refresh(audit_event)
            assert audit_event.legal_hold_until is not None
            assert audit_event.actor_user_id == user.id
            assert audit_event.reason == "manual review"
            assert audit_event.metadata_json == {"case": "retention"}
            assert audit_event.ip_address == "192.0.2.20"
            assert audit_event.user_agent == "Browser/2.0"

    run_async(_run())


def test_privacy_retention_defers_storage_deletion_until_database_steps_pass(
    monkeypatch,
    migrated_session_factory,
) -> None:
    class RetentionStepFailure(RuntimeError):
        pass

    async def _run() -> None:
        async with migrated_session_factory() as session:
            artifact_id, storage_key, dsr_id = await _create_expired_ready_artifact(
                session
            )
            service = ExportArtifactService(session)

            async def _fail_dsr_idempotency_cleanup(
                session,
                *,
                now: datetime,
                limit: int,
                dry_run: bool,
            ) -> int:
                raise RetentionStepFailure("database-only retention failed")

            monkeypatch.setattr(
                privacy_maintenance,
                "_clean_expired_dsr_idempotency_keys",
                _fail_dsr_idempotency_cleanup,
            )

            with pytest.raises(RetentionStepFailure):
                await privacy_maintenance.run_privacy_retention_maintenance(session)

            persisted_artifact = await service.repo.get_by_id(artifact_id)
            assert persisted_artifact is not None
            assert persisted_artifact.status == ExportArtifactStatus.READY.value
            assert persisted_artifact.storage_key == storage_key
            assert service.storage.exists(storage_key) is True
            persisted_dsr = await service.dsr_repo.get_by_id(dsr_id)
            assert persisted_dsr is not None
            assert (
                persisted_dsr.execution_status
                == DataSubjectRequestExecutionStatus.READY.value
            )

    run_async(_run())

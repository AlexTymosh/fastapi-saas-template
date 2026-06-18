from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.audit.models.audit_event import AuditCategory, AuditEvent, AuditTargetType
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.platform.models.platform_staff import PlatformStaff
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data import CrossTableSubjectDataExporter
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


def _export_context(subject_user_id: UUID, now: datetime) -> ExportContext:
    return ExportContext(
        artifact_id=uuid4(),
        data_subject_request_id=uuid4(),
        subject_user_id=subject_user_id,
        requester_user_id=subject_user_id,
        request_type="export",
        request_status=DataSubjectRequestStatus.APPROVED.value,
        generated_at=now,
        schema_version="1.0",
    )


async def _export_payload(session, *, subject_user_id: UUID, now: datetime):
    return await CrossTableSubjectDataExporter(session).export_subject_data(
        _export_context(subject_user_id, now)
    )


def _records_by_id(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(record["payload"]["id"]): record for record in records}


def test_invite_locator_matches_subject_email_and_revoker_paths(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"subject-{uuid4()}@example.com",
                email_verified=True,
            )
            invitee = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"invitee-{uuid4()}@example.com",
                email_verified=True,
            )
            organisation = Organisation(
                name="Subject Locator Org",
                slug=f"locator-{uuid4()}",
            )
            session.add_all([subject, invitee, organisation])
            await session.flush()

            email_match = Invite(
                email=subject.email.upper(),
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash="email-match-token-hash",
                expires_at=now + timedelta(days=1),
            )
            revoked_by_subject = Invite(
                email=invitee.email,
                organisation_id=organisation.id,
                role=MembershipRole.ADMIN,
                status=InviteStatus.REVOKED,
                token_hash="revoked-by-subject-token-hash",
                expires_at=now + timedelta(days=1),
                revoked_at=now,
                revoked_by_user_id=subject.id,
            )
            unrelated = Invite(
                email=f"unrelated-{uuid4()}@example.com",
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash="unrelated-token-hash",
                expires_at=now + timedelta(days=1),
            )
            session.add_all([email_match, revoked_by_subject, unrelated])
            await session.flush()

            payload = await _export_payload(
                session,
                subject_user_id=subject.id,
                now=now,
            )

            records = payload["data"]["invites.by_subject_email_or_revoker"]
            invite_records = _records_by_id(records)
            email_record = invite_records[str(email_match.id)]
            revoker_record = invite_records[str(revoked_by_subject.id)]

            assert str(unrelated.id) not in invite_records
            assert email_record["record_kind"] == "data"
            assert email_record["payload"]["email"] == subject.email.upper()
            assert revoker_record["record_kind"] == "reference"
            assert revoker_record["payload"]["revoked_by_user_id"] == str(subject.id)
            assert "email" not in revoker_record["payload"]

    run_async(_run())


def test_audit_locator_joins_subject_owned_targets(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            actor = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-actor-{uuid4()}@example.com",
                email_verified=True,
            )
            organisation = Organisation(
                name="Audit Locator Org",
                slug=f"audit-locator-{uuid4()}",
            )
            session.add_all([subject, actor, organisation])
            await session.flush()

            membership = Membership(
                user_id=subject.id,
                organisation_id=organisation.id,
                role=MembershipRole.ADMIN,
            )
            invite = Invite(
                email=subject.email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash="subject-invite-token-hash",
                expires_at=now + timedelta(days=1),
            )
            dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=subject.id,
                subject_user_id=subject.id,
                submitted_at=now,
                due_at=now + timedelta(days=30),
            )
            staff = PlatformStaff(
                user_id=subject.id,
                role="compliance_officer",
                status="active",
            )
            session.add_all([membership, invite, dsr, staff])
            await session.flush()

            artifact = ExportArtifact(
                data_subject_request_id=dsr.id,
                subject_user_id=subject.id,
                requester_user_id=subject.id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/artifact.zip",
                filename="subject-owned-export.zip",
                content_type="application/zip",
                size_bytes=128,
                checksum_sha256="a" * 64,
                schema_version="1.0",
                queued_at=now - timedelta(hours=1),
                started_at=now - timedelta(minutes=45),
                completed_at=now - timedelta(minutes=30),
                expires_at=now + timedelta(days=7),
                download_count=0,
            )
            session.add(artifact)
            await session.flush()

            events = [
                _audit_event(actor.id, "target_user", AuditTargetType.USER, subject.id),
                _audit_event(
                    actor.id,
                    "target_invite",
                    AuditTargetType.INVITE,
                    invite.id,
                ),
                _audit_event(
                    actor.id,
                    "target_membership",
                    AuditTargetType.MEMBERSHIP,
                    membership.id,
                ),
                _audit_event(
                    actor.id,
                    "target_dsr",
                    AuditTargetType.DATA_SUBJECT_REQUEST,
                    dsr.id,
                ),
                _audit_event(
                    actor.id,
                    "target_artifact",
                    AuditTargetType.EXPORT_ARTIFACT,
                    artifact.id,
                ),
                _audit_event(
                    actor.id,
                    "target_staff",
                    AuditTargetType.PLATFORM_STAFF,
                    staff.id,
                ),
            ]
            session.add_all(events)
            await session.flush()

            payload = await _export_payload(
                session,
                subject_user_id=subject.id,
                now=now,
            )

            audit_records = payload["data"]["audit.subject_actor_or_target_join_events"]
            exported_actions = {record["payload"]["action"] for record in audit_records}

            assert {
                "target_user",
                "target_invite",
                "target_membership",
                "target_dsr",
                "target_artifact",
                "target_staff",
            }.issubset(exported_actions)

    run_async(_run())


def test_actor_side_locators_export_reference_records(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"actor-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            owner = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"actor-owner-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([subject, owner])
            await session.flush()

            reviewed_dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=owner.id,
                subject_user_id=owner.id,
                reviewer_user_id=subject.id,
                submitted_at=now - timedelta(days=1),
                reviewed_at=now,
                due_at=now + timedelta(days=29),
            )
            session.add(reviewed_dsr)
            await session.flush()

            actor_artifact = ExportArtifact(
                data_subject_request_id=reviewed_dsr.id,
                subject_user_id=owner.id,
                requester_user_id=owner.id,
                requested_by_user_id=subject.id,
                generated_by_user_id=subject.id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/actor-only.zip",
                filename="other-subject-export.zip",
                content_type="application/zip",
                size_bytes=128,
                checksum_sha256="b" * 64,
                schema_version="1.0",
                queued_at=now - timedelta(hours=1),
                started_at=now - timedelta(minutes=45),
                completed_at=now - timedelta(minutes=30),
                expires_at=now + timedelta(days=7),
                download_count=0,
            )
            creator_staff = PlatformStaff(
                user_id=owner.id,
                role="compliance_officer",
                status="active",
                created_by_user_id=subject.id,
            )
            session.add_all([actor_artifact, creator_staff])
            await session.flush()

            payload = await _export_payload(
                session,
                subject_user_id=subject.id,
                now=now,
            )

            dsr_records = _records_by_id(payload["data"]["dsr.workflow_records"])
            artifact_records = _records_by_id(
                payload["data"]["export_artifacts.subject_or_actor_metadata"]
            )
            staff_records = _records_by_id(
                payload["data"]["platform_staff.by_subject_or_creator"]
            )
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert dsr_records[str(reviewed_dsr.id)]["record_kind"] == "reference"
            artifact_record = artifact_records[str(actor_artifact.id)]
            assert artifact_record["record_kind"] == "reference"
            assert staff_records[str(creator_staff.id)]["record_kind"] == "reference"
            assert owner.email not in encoded_payload
            assert "other-subject-export.zip" not in encoded_payload

    run_async(_run())


def _audit_event(
    actor_user_id: UUID,
    action: str,
    target_type: AuditTargetType,
    target_id: UUID,
) -> AuditEvent:
    return AuditEvent(
        actor_user_id=actor_user_id,
        category=AuditCategory.COMPLIANCE.value,
        action=action,
        target_type=target_type.value,
        target_id=target_id,
        created_at=datetime.now(UTC),
    )

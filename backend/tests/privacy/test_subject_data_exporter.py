from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType
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
from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    LawfulBasis,
    PrivacyNoticeAcceptance,
    ProcessingPurpose,
    ProcessingPurposeFamily,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


def test_cross_table_subject_export_includes_current_dsr_scope(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"{uuid4()}@example.com",
                email_verified=True,
                first_name="Ada",
                last_name="Lovelace",
                suspended_reason="Contains free-text user suspension note",
            )
            organisation = Organisation(
                name="Example Ltd",
                slug=f"org-{uuid4()}",
                suspended_reason="Contains free-text organisation review note",
            )
            session.add_all([user, organisation])
            await session.flush()

            membership = Membership(
                user_id=user.id,
                organisation_id=organisation.id,
                role=MembershipRole.ADMIN,
            )
            invite = Invite(
                email=user.email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash="secret-token-hash",
                expires_at=now + timedelta(days=1),
            )
            purpose = ProcessingPurpose(
                code=f"account-{uuid4()}",
                title="Account management",
                family=ProcessingPurposeFamily.ACCOUNT.value,
                default_lawful_basis=LawfulBasis.CONTRACT.value,
            )
            dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=user.id,
                subject_user_id=user.id,
                submitted_at=now,
                due_at=now + timedelta(days=30),
            )
            session.add_all([membership, invite, purpose, dsr])
            await session.flush()

            outbox = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json={
                    "invite_id": str(invite.id),
                    "organisation_id": str(organisation.id),
                    "email": user.email,
                    "encrypted_raw_token": "encrypted-secret-token",
                    "purpose": "created",
                    "role": MembershipRole.MEMBER.value,
                },
            )
            audit = AuditEvent(
                actor_user_id=user.id,
                category=AuditCategory.COMPLIANCE.value,
                action=AuditAction.DATA_SUBJECT_REQUEST_APPROVED.value,
                target_type="data_subject_request",
                target_id=dsr.id,
                reason="internal free text must not be exported",
                metadata_json={"request_type": "export", "unsafe": user.email},
            )
            authorization = DataProcessingAuthorization(
                subject_user_id=user.id,
                purpose_id=purpose.id,
                lawful_basis=LawfulBasis.CONTRACT.value,
                active=True,
            )
            consent = ConsentRecord(
                subject_user_id=user.id,
                purpose_id=purpose.id,
                privacy_notice_version="2026-01",
                granted_at=now,
            )
            notice = PrivacyNoticeAcceptance(
                subject_user_id=user.id,
                notice_version="2026-01",
                accepted_at=now,
                source="web",
            )
            session.add_all([outbox, audit, authorization, consent, notice])
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=dsr.id,
                    subject_user_id=user.id,
                    requester_user_id=user.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            assert payload["subject_user_id"] == str(user.id)
            assert payload["request_type"] == "export"
            data = payload["data"]
            assert data["users.profile"]
            user_record = data["users.profile"][0]
            user_payload = user_record["payload"]
            assert "suspended_reason" not in user_payload
            assert "suspended_reason" in user_record["redacted_fields"]
            assert data["memberships.by_subject"]
            assert data["organisations.by_subject_membership"]
            org_record = data["organisations.by_subject_membership"][0]
            org_payload = org_record["payload"]
            assert "suspended_reason" not in org_payload
            assert "suspended_reason" in org_record["redacted_fields"]
            assert data["invites.by_subject_email_or_revoker"]
            assert data["outbox.subject_references"]
            assert data["audit.subject_actor_or_target_join_events"]
            assert data["dsr.workflow_records"]
            assert data["privacy_governance.authorizations"]
            assert data["privacy_governance.consent_records"]
            assert data["privacy_governance.notice_acceptances"]

            invite_payload = data["invites.by_subject_email_or_revoker"][0]["payload"]
            assert "token_hash" not in invite_payload
            outbox_payload = data["outbox.subject_references"][0]["payload"]
            assert "payload_json" not in outbox_payload
            assert outbox_payload["payload_reference"]["invite_id"] == str(invite.id)
            assert "email" not in outbox_payload["payload_reference"]
            assert "encrypted_raw_token" not in outbox_payload["payload_reference"]

            audit_payload = data["audit.subject_actor_or_target_join_events"][0][
                "payload"
            ]
            assert "reason" not in audit_payload
            assert audit_payload["metadata_json"] == {"request_type": "export"}
            notices = payload["manifest"]["redaction_notices"]
            assert notices
            encoded_payload = json.dumps(payload, sort_keys=True)
            assert "Contains free-text user suspension note" not in encoded_payload
            assert "Contains free-text organisation review note" not in encoded_payload

    run_async(_run())


def test_dsr_export_minimises_reviewer_only_requests(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            reviewer = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"reviewer-{uuid4()}@example.com",
                email_verified=True,
                first_name="Reviewer",
            )
            requester = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"requester-{uuid4()}@example.com",
                email_verified=True,
                first_name="Requester",
            )
            session.add_all([reviewer, requester])
            await session.flush()

            reviewed_dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=requester.id,
                subject_user_id=requester.id,
                reviewer_user_id=reviewer.id,
                requester_note="Other subject private note",
                internal_note="Internal reviewer note",
                submitted_at=now - timedelta(days=1),
                reviewed_at=now,
                decided_at=now,
                due_at=now + timedelta(days=29),
            )
            session.add(reviewed_dsr)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=reviewer.id,
                    requester_user_id=reviewer.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["dsr.workflow_records"]
            reviewer_record = next(
                item
                for item in records
                if item["payload"]["id"] == str(reviewed_dsr.id)
            )
            reviewer_payload = reviewer_record["payload"]
            redacted_fields = set(reviewer_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert reviewer_record["record_kind"] == "reference"
            assert reviewer_payload["reviewer_user_id"] == str(reviewer.id)
            assert reviewer_payload["status"] == DataSubjectRequestStatus.APPROVED.value
            assert "requester_user_id" not in reviewer_payload
            assert "subject_user_id" not in reviewer_payload
            assert "requester_note" not in reviewer_payload
            assert "internal_note" not in reviewer_payload
            assert "requester_user_id" in redacted_fields
            assert "subject_user_id" in redacted_fields
            assert "requester_note" in redacted_fields
            assert str(requester.id) not in encoded_payload
            assert requester.email not in encoded_payload
            assert "Other subject private note" not in encoded_payload

    run_async(_run())


def test_export_minimises_actor_only_export_artifact_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            actor = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"actor-{uuid4()}@example.com",
                email_verified=True,
                first_name="Actor",
            )
            requester = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"artifact-owner-{uuid4()}@example.com",
                email_verified=True,
                first_name="Owner",
            )
            session.add_all([actor, requester])
            await session.flush()

            other_dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=requester.id,
                subject_user_id=requester.id,
                submitted_at=now - timedelta(days=1),
                due_at=now + timedelta(days=29),
            )
            session.add(other_dsr)
            await session.flush()

            actor_artifact = ExportArtifact(
                data_subject_request_id=other_dsr.id,
                subject_user_id=requester.id,
                requester_user_id=requester.id,
                requested_by_user_id=actor.id,
                generated_by_user_id=actor.id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/artifact.zip",
                filename="privacy-export-other-subject.zip",
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
            session.add(actor_artifact)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=actor.id,
                    requester_user_id=actor.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["export_artifacts.subject_or_actor_metadata"]
            artifact_record = next(
                item
                for item in records
                if item["payload"]["id"] == str(actor_artifact.id)
            )
            artifact_payload = artifact_record["payload"]
            redacted_fields = set(artifact_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert artifact_record["record_kind"] == "reference"
            assert artifact_payload["requested_by_user_id"] == str(actor.id)
            assert artifact_payload["generated_by_user_id"] == str(actor.id)
            assert artifact_payload["status"] == ExportArtifactStatus.READY.value
            assert "data_subject_request_id" not in artifact_payload
            assert "subject_user_id" not in artifact_payload
            assert "requester_user_id" not in artifact_payload
            assert "filename" not in artifact_payload
            assert "checksum_sha256" not in artifact_payload
            assert "data_subject_request_id" in redacted_fields
            assert "subject_user_id" in redacted_fields
            assert "requester_user_id" in redacted_fields
            assert "filename" in redacted_fields
            assert str(requester.id) not in encoded_payload
            assert str(other_dsr.id) not in encoded_payload
            assert requester.email not in encoded_payload
            assert "privacy-export-other-subject.zip" not in encoded_payload

    run_async(_run())


def test_invite_export_minimises_revoker_only_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            revoker = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"revoker-{uuid4()}@example.com",
                email_verified=True,
            )
            invitee = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"invitee-{uuid4()}@example.com",
                email_verified=True,
            )
            organisation = Organisation(name="Sensitive Org", slug=f"org-{uuid4()}")
            session.add_all([revoker, invitee, organisation])
            await session.flush()

            invite = Invite(
                email=invitee.email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.REVOKED,
                token_hash="secret-token-hash",
                expires_at=now + timedelta(days=1),
                revoked_at=now,
                revoked_by_user_id=revoker.id,
            )
            session.add(invite)
            await session.flush()

            outbox = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=invite.id,
                payload_json={
                    "invite_id": str(invite.id),
                    "organisation_id": str(organisation.id),
                    "email": invitee.email,
                    "encrypted_raw_token": "encrypted-secret-token",
                    "role": MembershipRole.MEMBER.value,
                },
            )
            session.add(outbox)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=revoker.id,
                    requester_user_id=revoker.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            invite_records = payload["data"]["invites.by_subject_email_or_revoker"]
            invite_record = next(
                item
                for item in invite_records
                if item["payload"]["id"] == str(invite.id)
            )
            invite_payload = invite_record["payload"]
            redacted_fields = set(invite_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert invite_record["record_kind"] == "reference"
            assert invite_payload["revoked_by_user_id"] == str(revoker.id)
            assert invite_payload["status"] == InviteStatus.REVOKED.value
            assert "email" not in invite_payload
            assert "organisation_id" not in invite_payload
            assert "role" not in invite_payload
            assert "expires_at" not in invite_payload
            assert "email" in redacted_fields
            assert "organisation_id" in redacted_fields
            assert "role" in redacted_fields
            assert "token_hash" in redacted_fields
            assert payload["data"]["outbox.subject_references"] == []
            assert str(invitee.id) not in encoded_payload
            assert invitee.email not in encoded_payload
            assert str(organisation.id) not in encoded_payload

    run_async(_run())


def test_platform_staff_export_minimises_creator_only_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            creator = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"creator-{uuid4()}@example.com",
                email_verified=True,
            )
            staff_user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"staff-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([creator, staff_user])
            await session.flush()

            staff = PlatformStaff(
                user_id=staff_user.id,
                role="compliance_officer",
                status="suspended",
                created_by_user_id=creator.id,
                suspended_at=now,
                suspended_reason="Private staff suspension note",
            )
            session.add(staff)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=creator.id,
                    requester_user_id=creator.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["platform_staff.by_subject_or_creator"]
            creator_record = next(
                item for item in records if item["payload"]["id"] == str(staff.id)
            )
            creator_payload = creator_record["payload"]
            redacted_fields = set(creator_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert creator_record["record_kind"] == "reference"
            assert creator_payload["created_by_user_id"] == str(creator.id)
            assert "user_id" not in creator_payload
            assert "role" not in creator_payload
            assert "status" not in creator_payload
            assert "suspended_at" not in creator_payload
            assert "suspended_reason" not in creator_payload
            assert "user_id" in redacted_fields
            assert "role" in redacted_fields
            assert "status" in redacted_fields
            assert "suspended_reason" in redacted_fields
            assert str(staff_user.id) not in encoded_payload
            assert staff_user.email not in encoded_payload
            assert "Private staff suspension note" not in encoded_payload

    run_async(_run())


def test_platform_staff_export_redacts_free_text_suspension_reason(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            staff_user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"staff-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(staff_user)
            await session.flush()

            staff = PlatformStaff(
                user_id=staff_user.id,
                role="compliance_officer",
                status="suspended",
                created_by_user_id=staff_user.id,
                suspended_at=now,
                suspended_reason="Free text staff reason",
            )
            session.add(staff)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=staff_user.id,
                    requester_user_id=staff_user.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["platform_staff.by_subject_or_creator"]
            subject_record = next(
                item for item in records if item["payload"]["id"] == str(staff.id)
            )
            subject_payload = subject_record["payload"]

            assert subject_record["record_kind"] == "data"
            assert subject_payload["user_id"] == str(staff_user.id)
            assert subject_payload["role"] == "compliance_officer"
            assert subject_payload["status"] == "suspended"
            assert "suspended_reason" not in subject_payload
            assert "suspended_reason" in subject_record["redacted_fields"]
            assert "Free text staff reason" not in json.dumps(payload)

    run_async(_run())


def test_audit_export_minimises_non_subject_actor_fields(
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
            staff_actor = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-staff-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([subject, staff_actor])
            await session.flush()

            audit_event = AuditEvent(
                actor_user_id=staff_actor.id,
                category=AuditCategory.COMPLIANCE.value,
                action="user_suspended",
                target_type=AuditTargetType.USER.value,
                target_id=subject.id,
                reason="internal free text must not be exported",
                metadata_json={"status": "suspended", "unsafe": staff_actor.email},
                ip_address="203.0.113.10",
                user_agent="staff-admin-browser",
                created_at=now,
            )
            session.add(audit_event)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=subject.id,
                    requester_user_id=subject.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["audit.subject_actor_or_target_join_events"]
            audit_record = next(
                item for item in records if item["payload"]["id"] == str(audit_event.id)
            )
            audit_payload = audit_record["payload"]
            redacted_fields = set(audit_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert audit_payload["target_type"] == AuditTargetType.USER.value
            assert audit_payload["target_id"] == str(subject.id)
            assert audit_payload["has_actor"] is True
            assert "actor_user_id" not in audit_payload
            assert "ip_address" not in audit_payload
            assert "user_agent" not in audit_payload
            assert "actor_user_id" in redacted_fields
            assert "ip_address" in redacted_fields
            assert "user_agent" in redacted_fields
            assert "metadata_json.unsafe" in redacted_fields
            assert str(staff_actor.id) not in encoded_payload
            assert staff_actor.email not in encoded_payload
            assert "203.0.113.10" not in encoded_payload
            assert "staff-admin-browser" not in encoded_payload

    run_async(_run())


def test_dsr_export_redacts_non_subject_reviewer_from_subject_records(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"dsr-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            reviewer = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"dsr-reviewer-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([subject, reviewer])
            await session.flush()

            dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=subject.id,
                subject_user_id=subject.id,
                reviewer_user_id=reviewer.id,
                requester_note="Subject visible request note",
                submitted_at=now - timedelta(days=1),
                reviewed_at=now,
                due_at=now + timedelta(days=29),
            )
            session.add(dsr)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=subject.id,
                    requester_user_id=subject.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["dsr.workflow_records"]
            dsr_record = next(
                item for item in records if item["payload"]["id"] == str(dsr.id)
            )
            dsr_payload = dsr_record["payload"]
            redacted_fields = set(dsr_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert dsr_record["record_kind"] == "data"
            assert dsr_payload["subject_user_id"] == str(subject.id)
            assert dsr_payload["requester_user_id"] == str(subject.id)
            assert dsr_payload["has_reviewer"] is True
            assert "reviewer_user_id" not in dsr_payload
            assert "reviewer_user_id" in redacted_fields
            assert str(reviewer.id) not in encoded_payload
            assert reviewer.email not in encoded_payload

    run_async(_run())


def test_export_artifacts_redact_platform_actors_from_subject_owned_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"artifact-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            platform_actor = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"artifact-actor-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([subject, platform_actor])
            await session.flush()

            dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=subject.id,
                subject_user_id=subject.id,
                submitted_at=now - timedelta(days=1),
                due_at=now + timedelta(days=29),
            )
            session.add(dsr)
            await session.flush()

            artifact = ExportArtifact(
                data_subject_request_id=dsr.id,
                subject_user_id=subject.id,
                requester_user_id=subject.id,
                requested_by_user_id=platform_actor.id,
                generated_by_user_id=platform_actor.id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/artifact.zip",
                filename="privacy-export-subject.zip",
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
            session.add(artifact)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=subject.id,
                    requester_user_id=subject.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["export_artifacts.subject_or_actor_metadata"]
            artifact_record = next(
                item for item in records if item["payload"]["id"] == str(artifact.id)
            )
            artifact_payload = artifact_record["payload"]
            redacted_fields = set(artifact_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert artifact_record["record_kind"] == "data"
            assert artifact_payload["subject_user_id"] == str(subject.id)
            assert artifact_payload["requester_user_id"] == str(subject.id)
            assert artifact_payload["has_requested_by"] is True
            assert artifact_payload["has_generated_by"] is True
            assert "requested_by_user_id" not in artifact_payload
            assert "generated_by_user_id" not in artifact_payload
            assert "requested_by_user_id" in redacted_fields
            assert "generated_by_user_id" in redacted_fields
            assert str(platform_actor.id) not in encoded_payload
            assert platform_actor.email not in encoded_payload

    run_async(_run())


def test_invite_export_redacts_non_subject_revoker_from_subject_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            invitee = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"invite-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            revoker = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"invite-revoker-{uuid4()}@example.com",
                email_verified=True,
            )
            organisation = Organisation(name="Invite Org", slug=f"org-{uuid4()}")
            session.add_all([invitee, revoker, organisation])
            await session.flush()

            invite = Invite(
                email=invitee.email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.REVOKED,
                token_hash="secret-token-hash",
                expires_at=now + timedelta(days=1),
                revoked_at=now,
                revoked_by_user_id=revoker.id,
            )
            session.add(invite)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=invitee.id,
                    requester_user_id=invitee.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["invites.by_subject_email_or_revoker"]
            invite_record = next(
                item for item in records if item["payload"]["id"] == str(invite.id)
            )
            invite_payload = invite_record["payload"]
            redacted_fields = set(invite_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert invite_record["record_kind"] == "data"
            assert invite_payload["email"] == invitee.email
            assert invite_payload["has_revoker"] is True
            assert "revoked_by_user_id" not in invite_payload
            assert "revoked_by_user_id" in redacted_fields
            assert "token_hash" in redacted_fields
            assert str(revoker.id) not in encoded_payload
            assert revoker.email not in encoded_payload

    run_async(_run())


def test_platform_staff_export_redacts_non_subject_creator_from_subject_rows(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            staff_user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"staff-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            creator = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"staff-creator-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([staff_user, creator])
            await session.flush()

            staff = PlatformStaff(
                user_id=staff_user.id,
                role="compliance_officer",
                status="active",
                created_by_user_id=creator.id,
            )
            session.add(staff)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=staff_user.id,
                    requester_user_id=staff_user.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["platform_staff.by_subject_or_creator"]
            staff_record = next(
                item for item in records if item["payload"]["id"] == str(staff.id)
            )
            staff_payload = staff_record["payload"]
            redacted_fields = set(staff_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert staff_record["record_kind"] == "data"
            assert staff_payload["user_id"] == str(staff_user.id)
            assert staff_payload["role"] == "compliance_officer"
            assert staff_payload["status"] == "active"
            assert staff_payload["has_creator"] is True
            assert "created_by_user_id" not in staff_payload
            assert "created_by_user_id" in redacted_fields
            assert str(creator.id) not in encoded_payload
            assert creator.email not in encoded_payload

    run_async(_run())


def test_audit_export_omits_legal_hold_timestamps(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            legal_hold_until = datetime(2099, 1, 1, tzinfo=UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"legal-hold-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(subject)
            await session.flush()

            audit_event = AuditEvent(
                actor_user_id=subject.id,
                category=AuditCategory.COMPLIANCE.value,
                action="legal_hold_timestamp_marker",
                target_type=AuditTargetType.USER.value,
                target_id=subject.id,
                legal_hold_until=legal_hold_until,
                created_at=now,
            )
            session.add(audit_event)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=subject.id,
                    requester_user_id=subject.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["audit.subject_actor_or_target_join_events"]
            audit_record = next(
                item for item in records if item["payload"]["id"] == str(audit_event.id)
            )
            audit_payload = audit_record["payload"]
            redacted_fields = set(audit_record["redacted_fields"])
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert "legal_hold_until" not in audit_payload
            assert "legal_hold_until" in redacted_fields
            assert legal_hold_until.isoformat() not in encoded_payload

    run_async(_run())


def test_audit_export_does_not_join_actor_only_target_ids(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-actor-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            owner = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-target-owner-{uuid4()}@example.com",
                email_verified=True,
            )
            other_actor = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"audit-other-actor-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([subject, owner, other_actor])
            await session.flush()

            reviewer_only_dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=owner.id,
                subject_user_id=owner.id,
                reviewer_user_id=subject.id,
                submitted_at=now - timedelta(days=1),
                reviewed_at=now,
                due_at=now + timedelta(days=29),
            )
            session.add(reviewer_only_dsr)
            await session.flush()

            actor_only_artifact = ExportArtifact(
                data_subject_request_id=reviewer_only_dsr.id,
                subject_user_id=owner.id,
                requester_user_id=owner.id,
                requested_by_user_id=subject.id,
                generated_by_user_id=subject.id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/artifact.zip",
                filename="privacy-export-other-subject.zip",
                content_type="application/zip",
                size_bytes=128,
                checksum_sha256="c" * 64,
                schema_version="1.0",
                queued_at=now - timedelta(hours=1),
                started_at=now - timedelta(minutes=45),
                completed_at=now - timedelta(minutes=30),
                expires_at=now + timedelta(days=7),
                download_count=0,
            )
            creator_only_staff = PlatformStaff(
                user_id=owner.id,
                role="compliance_officer",
                status="active",
                created_by_user_id=subject.id,
            )
            session.add_all([actor_only_artifact, creator_only_staff])
            await session.flush()

            audit_events = [
                AuditEvent(
                    actor_user_id=other_actor.id,
                    category=AuditCategory.COMPLIANCE.value,
                    action="reviewer_only_dsr_target_join_marker",
                    target_type=AuditTargetType.DATA_SUBJECT_REQUEST.value,
                    target_id=reviewer_only_dsr.id,
                    created_at=now,
                ),
                AuditEvent(
                    actor_user_id=other_actor.id,
                    category=AuditCategory.COMPLIANCE.value,
                    action="actor_only_artifact_target_join_marker",
                    target_type=AuditTargetType.EXPORT_ARTIFACT.value,
                    target_id=actor_only_artifact.id,
                    created_at=now,
                ),
                AuditEvent(
                    actor_user_id=other_actor.id,
                    category=AuditCategory.COMPLIANCE.value,
                    action="creator_only_staff_target_join_marker",
                    target_type=AuditTargetType.PLATFORM_STAFF.value,
                    target_id=creator_only_staff.id,
                    created_at=now,
                ),
            ]
            session.add_all(audit_events)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=subject.id,
                    requester_user_id=subject.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["audit.subject_actor_or_target_join_events"]
            exported_audit_ids = {item["payload"]["id"] for item in records}
            encoded_payload = json.dumps(payload, sort_keys=True)

            assert str(audit_events[0].id) not in exported_audit_ids
            assert str(audit_events[1].id) not in exported_audit_ids
            assert str(audit_events[2].id) not in exported_audit_ids
            assert "reviewer_only_dsr_target_join_marker" not in encoded_payload
            assert "actor_only_artifact_target_join_marker" not in encoded_payload
            assert "creator_only_staff_target_join_marker" not in encoded_payload
            assert other_actor.email not in encoded_payload

    run_async(_run())


def test_export_artifact_provider_omits_non_ready_artifacts(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"artifact-subject-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(subject)
            await session.flush()

            dsr = DataSubjectRequest(
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=subject.id,
                subject_user_id=subject.id,
                submitted_at=now - timedelta(days=1),
                due_at=now + timedelta(days=29),
            )
            session.add(dsr)
            await session.flush()

            ready_artifact = ExportArtifact(
                data_subject_request_id=dsr.id,
                subject_user_id=subject.id,
                requester_user_id=subject.id,
                status=ExportArtifactStatus.READY.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/ready.zip",
                filename="privacy-export-ready.zip",
                content_type="application/zip",
                size_bytes=256,
                checksum_sha256="a" * 64,
                schema_version="1.0",
                queued_at=now - timedelta(hours=2),
                started_at=now - timedelta(hours=1),
                completed_at=now - timedelta(minutes=30),
                expires_at=now + timedelta(days=7),
                download_count=0,
            )
            processing_artifact = ExportArtifact(
                data_subject_request_id=dsr.id,
                subject_user_id=subject.id,
                requester_user_id=subject.id,
                status=ExportArtifactStatus.PROCESSING.value,
                format=ExportArtifactFormat.JSON_ZIP.value,
                storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                storage_key=f"exports/{uuid4()}/processing.zip",
                filename="privacy-export-processing.zip",
                content_type="application/zip",
                size_bytes=None,
                checksum_sha256=None,
                schema_version="1.0",
                queued_at=now - timedelta(minutes=5),
                started_at=now - timedelta(minutes=4),
                expires_at=now + timedelta(days=7),
                download_count=0,
            )
            session.add_all([ready_artifact, processing_artifact])
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=processing_artifact.id,
                    data_subject_request_id=dsr.id,
                    subject_user_id=subject.id,
                    requester_user_id=subject.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["export_artifacts.subject_or_actor_metadata"]
            artifact_records_json = json.dumps(records, sort_keys=True)

            assert any(
                item["payload"]["id"] == str(ready_artifact.id) for item in records
            )
            assert all(
                item["payload"]["id"] != str(processing_artifact.id) for item in records
            )
            assert "privacy-export-ready.zip" in artifact_records_json
            assert "privacy-export-processing.zip" not in artifact_records_json
            assert str(processing_artifact.id) not in artifact_records_json

    run_async(_run())

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.audit.models.audit_event import AuditAction, AuditCategory, AuditEvent
from app.invites.models.invite import Invite, InviteStatus
from app.memberships.models.membership import Membership, MembershipRole
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data import CrossTableSubjectDataExporter
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
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
            )
            organisation = Organisation(name="Example Ltd", slug=f"org-{uuid4()}")
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
            assert data["memberships.by_subject"]
            assert data["organisations.by_subject_membership"]
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

    run_async(_run())

from __future__ import annotations

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
from app.memberships.models.membership import MembershipRole
from app.organisations.models.organisation import Organisation
from app.outbox.models.outbox_event import OutboxEvent, OutboxStatus
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data import CrossTableSubjectDataExporter
from app.privacy.models.data_subject_request import DataSubjectRequestStatus
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


def test_audit_invite_lookup_normalises_subject_email(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            email_token = uuid4().hex
            legacy_email = f"  Legacy-{email_token}@Example.COM  "
            normalised_email = legacy_email.strip().lower()
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=legacy_email,
                email_verified=True,
            )
            organisation = Organisation(
                name="Email Normalisation Org",
                slug=f"email-normalisation-{uuid4()}",
            )
            session.add_all([user, organisation])
            await session.flush()

            invite = Invite(
                email=normalised_email,
                organisation_id=organisation.id,
                role=MembershipRole.MEMBER,
                status=InviteStatus.PENDING,
                token_hash="secret-token-hash",
                expires_at=now + timedelta(days=1),
            )
            session.add(invite)
            await session.flush()

            audit = AuditEvent(
                actor_user_id=None,
                category=AuditCategory.COMPLIANCE.value,
                action=AuditAction.DATA_SUBJECT_REQUEST_APPROVED.value,
                target_type=AuditTargetType.INVITE.value,
                target_id=invite.id,
                metadata_json={"invite_status_before": InviteStatus.PENDING.value},
            )
            session.add(audit)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=user.id,
                    requester_user_id=user.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            invite_records = payload["data"]["invites.by_subject_email_or_revoker"]
            audit_records = payload["data"]["audit.subject_actor_or_target_join_events"]

            assert any(
                record["payload"]["id"] == str(invite.id) for record in invite_records
            )
            assert any(
                record["payload"]["id"] == str(audit.id) for record in audit_records
            )

    run_async(_run())


def test_outbox_payload_email_lookup_normalises_subject_email(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            email_token = uuid4().hex
            legacy_email = f"  Payload-{email_token}@Example.COM  "
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=legacy_email,
                email_verified=True,
            )
            session.add(user)
            await session.flush()

            outbox_event = OutboxEvent(
                event_type="invite.created",
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": legacy_email,
                    "invite_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-secret-token",
                    "purpose": "invite_delivery",
                },
                status=OutboxStatus.PENDING.value,
            )
            session.add(outbox_event)
            await session.flush()

            payload = await CrossTableSubjectDataExporter(session).export_subject_data(
                ExportContext(
                    artifact_id=uuid4(),
                    data_subject_request_id=uuid4(),
                    subject_user_id=user.id,
                    requester_user_id=user.id,
                    request_type="export",
                    request_status=DataSubjectRequestStatus.APPROVED.value,
                    generated_at=now,
                    schema_version="1.0",
                )
            )

            records = payload["data"]["outbox.subject_references"]
            matching_record = next(
                record
                for record in records
                if record["payload"]["id"] == str(outbox_event.id)
            )

            assert matching_record["payload"]["payload_reference"] == {
                "invite_id": outbox_event.payload_json["invite_id"],
                "purpose": "invite_delivery",
            }
            assert "payload_json.email" in matching_record["redacted_fields"]
            assert (
                "payload_json.encrypted_raw_token" in matching_record["redacted_fields"]
            )

    run_async(_run())

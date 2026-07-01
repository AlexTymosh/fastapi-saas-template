from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.privacy.erasures.impact import build_erasure_impact_preview
from app.privacy.erasures.outbox import scrub_outbox_for_approved_erase_request
from app.privacy.exporters.base import ExportContext
from app.privacy.exporters.subject_data import CrossTableSubjectDataExporter
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.users.models.user import User
from tests.fixtures.postgres import postgres_integration_url as postgres_integration_url
from tests.helpers.alembic import upgrade_database_to_head
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.integration, pytest.mark.container]


@pytest.fixture(scope="module")
def postgres_dsr_session_factory(
    postgres_integration_url: str,
) -> Iterator[async_sessionmaker[AsyncSession]]:
    upgrade_database_to_head(postgres_integration_url)
    engine = create_async_engine(postgres_integration_url)
    session_factory = async_sessionmaker(
        bind=engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    yield session_factory
    run_async(engine.dispose())


def test_postgresql_subject_export_uses_outbox_json_email_predicate(
    postgres_dsr_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with postgres_dsr_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"subject-{uuid4()}@example.com",
                email_verified=True,
            )
            other_user = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"other-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add_all([subject, other_user])
            await session.flush()

            matching_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": subject.email,
                    "invite_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-subject-token",
                    "purpose": "created",
                },
            )
            unrelated_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": other_user.email,
                    "invite_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-other-token",
                    "purpose": "created",
                },
            )
            session.add_all([matching_event, unrelated_event])
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

            records = payload["data"]["outbox.subject_references"]
            exported_event_ids = {item["payload"]["id"] for item in records}
            matching_record = next(
                item
                for item in records
                if item["payload"]["id"] == str(matching_event.id)
            )
            redacted_fields = set(matching_record["redacted_fields"])

            assert str(matching_event.id) in exported_event_ids
            assert str(unrelated_event.id) not in exported_event_ids
            assert matching_record["record_kind"] == "reference"
            assert "email" not in matching_record["payload"]["payload_reference"]
            assert "payload_json.email" in redacted_fields
            assert "payload_json.encrypted_raw_token" in redacted_fields

    run_async(_run())


def test_postgresql_erasure_preview_counts_outbox_json_email_predicate(
    postgres_dsr_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with postgres_dsr_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"subject-preview-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(subject)
            await session.flush()

            erase_request = DataSubjectRequest(
                request_type=DataSubjectRequestType.ERASE.value,
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=subject.id,
                subject_user_id=subject.id,
                submitted_at=now - timedelta(days=1),
                due_at=now + timedelta(days=29),
            )
            matching_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": f"  {subject.email.upper()}  ",
                    "invite_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-subject-token",
                },
            )
            unrelated_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": f"unrelated-{uuid4()}@example.com",
                    "invite_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-other-token",
                },
            )
            session.add_all([erase_request, matching_event, unrelated_event])
            await session.flush()

            preview = await build_erasure_impact_preview(session, erase_request)
            row_counts = {
                entry.provider_key: entry.estimated_rows for entry in preview.entries
            }

            assert row_counts["outbox.purge_or_scrub_payload"] == 1

    run_async(_run())


def test_postgresql_outbox_erasure_scrubs_json_email_predicate_rows(
    postgres_dsr_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async def _run() -> None:
        async with postgres_dsr_session_factory() as session:
            now = datetime.now(UTC)
            subject = User(
                external_auth_id=f"kc|{uuid4()}",
                email=f"subject-scrub-{uuid4()}@example.com",
                email_verified=True,
            )
            session.add(subject)
            await session.flush()

            erase_request = DataSubjectRequest(
                request_type=DataSubjectRequestType.ERASE.value,
                status=DataSubjectRequestStatus.APPROVED.value,
                requester_user_id=subject.id,
                subject_user_id=subject.id,
                submitted_at=now - timedelta(days=1),
                due_at=now + timedelta(days=29),
            )
            matching_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": f"  {subject.email.upper()}  ",
                    "invite_id": str(uuid4()),
                    "organisation_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-subject-token",
                    "role": "member",
                },
            )
            unrelated_event = OutboxEvent(
                event_type=OutboxEventType.INVITE_CREATED.value,
                aggregate_type="invite",
                aggregate_id=uuid4(),
                payload_json={
                    "email": f"unrelated-{uuid4()}@example.com",
                    "invite_id": str(uuid4()),
                    "encrypted_raw_token": "encrypted-other-token",
                },
            )
            session.add_all([erase_request, matching_event, unrelated_event])
            await session.flush()

            result = await scrub_outbox_for_approved_erase_request(
                session,
                erase_request,
            )
            await session.flush()

            assert result.affected_rows == 1
            assert matching_event.status == OutboxStatus.FAILED.value
            assert matching_event.payload_json["privacy_erasure_scrubbed"] is True
            assert matching_event.payload_json["sensitive_payload_scrubbed"] is True
            assert "email" not in matching_event.payload_json
            assert "encrypted_raw_token" not in matching_event.payload_json
            assert unrelated_event.status == OutboxStatus.PENDING.value
            assert "privacy_erasure_scrubbed" not in unrelated_event.payload_json

    run_async(_run())

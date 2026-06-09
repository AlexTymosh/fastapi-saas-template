from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from sqlalchemy import select

from app.audit.models.audit_event import AuditAction, AuditEvent
from app.core.platform.permissions import PlatformRole
from app.outbox.models.outbox_event import OutboxEvent, OutboxEventType, OutboxStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.privacy, pytest.mark.security, pytest.mark.authz]


def _provision_user(session_factory, external_auth_id: str, email: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
            return user

    return run_async(_run())


def _provision_platform_actor(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: PlatformRole,
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
            return user

    return run_async(_run())


def _create_approved_erase_dsr(session_factory, subject):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                dsr = DataSubjectRequest(
                    request_type="erase",
                    status=DataSubjectRequestStatus.APPROVED.value,
                    requester_user_id=subject.id,
                    subject_user_id=subject.id,
                    submitted_at=datetime.now(UTC),
                    reviewed_at=datetime.now(UTC),
                    decided_at=datetime.now(UTC),
                    due_at=datetime.now(UTC),
                )
                session.add(dsr)
                await session.flush()
                return dsr.id

    return run_async(_run())


def _create_pending_invite_outbox(session_factory, *, subject_email: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                invite_id = uuid4()
                outbox = OutboxEvent(
                    event_type=OutboxEventType.INVITE_CREATED.value,
                    aggregate_type="invite",
                    aggregate_id=invite_id,
                    payload_json={
                        "invite_id": str(invite_id),
                        "organisation_id": str(uuid4()),
                        "email": subject_email,
                        "encrypted_raw_token": "encrypted-secret-token",
                        "purpose": "created",
                        "role": "member",
                    },
                    status=OutboxStatus.PENDING.value,
                )
                session.add(outbox)
                await session.flush()
                return outbox.id

    return run_async(_run())


def _create_processing_invite_outbox(session_factory, *, subject_email: str):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                invite_id = uuid4()
                outbox = OutboxEvent(
                    event_type=OutboxEventType.INVITE_CREATED.value,
                    aggregate_type="invite",
                    aggregate_id=invite_id,
                    payload_json={
                        "invite_id": str(invite_id),
                        "organisation_id": str(uuid4()),
                        "email": subject_email,
                        "encrypted_raw_token": "encrypted-secret-token",
                        "purpose": "created",
                        "role": "member",
                    },
                    status=OutboxStatus.PROCESSING.value,
                    locked_at=datetime.now(UTC),
                )
                session.add(outbox)
                await session.flush()
                return outbox.id

    return run_async(_run())


def test_compliance_officer_can_execute_approved_erasure_via_platform_api(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    subject = _provision_user(
        migrated_session_factory,
        "kc-erasure-api-subject",
        "erasure-api-subject@example.com",
    )
    executor = _provision_platform_actor(
        migrated_session_factory,
        external_auth_id="kc-erasure-api-compliance",
        email="erasure-api-compliance@example.com",
        role=PlatformRole.COMPLIANCE_OFFICER,
    )
    dsr_id = _create_approved_erase_dsr(migrated_session_factory, subject)
    outbox_id = _create_pending_invite_outbox(
        migrated_session_factory,
        subject_email=subject.email,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(executor.external_auth_id, executor.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.post(
        f"/api/v1/platform/privacy/data-subject-requests/{dsr_id}/execute-erasure",
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(dsr_id)
    assert body["execution_status"] == DataSubjectRequestExecutionStatus.READY.value

    async def _assert_persisted_state() -> None:
        async with migrated_session_factory() as session:
            saved_subject = await UserService(session).user_repository.get_by_id(
                subject.id
            )
            saved_outbox = await session.get(OutboxEvent, outbox_id)
            audit_event = (
                await session.execute(
                    select(AuditEvent).where(
                        AuditEvent.action
                        == AuditAction.DATA_SUBJECT_REQUEST_ERASURE_EXECUTED.value,
                        AuditEvent.target_id == dsr_id,
                    )
                )
            ).scalar_one()

            assert saved_subject is not None
            assert saved_subject.email is None
            assert saved_outbox is not None
            assert saved_outbox.status == OutboxStatus.FAILED.value
            assert "email" not in saved_outbox.payload_json
            assert audit_event.actor_user_id == executor.id
            assert audit_event.metadata_json is not None
            assert audit_event.metadata_json["orchestration_status"] == "completed"

    run_async(_assert_persisted_state())


def test_support_agent_cannot_execute_erasure_via_platform_api(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    subject = _provision_user(
        migrated_session_factory,
        "kc-erasure-api-forbidden-subject",
        "erasure-api-forbidden-subject@example.com",
    )
    support = _provision_platform_actor(
        migrated_session_factory,
        external_auth_id="kc-erasure-api-support",
        email="erasure-api-support@example.com",
        role=PlatformRole.SUPPORT_AGENT,
    )
    dsr_id = _create_approved_erase_dsr(migrated_session_factory, subject)
    bundle = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.post(
        f"/api/v1/platform/privacy/data-subject-requests/{dsr_id}/execute-erasure",
        json={},
    )

    assert response.status_code == 403


def test_erasure_execution_api_rejects_missing_request(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    admin = _provision_platform_actor(
        migrated_session_factory,
        external_auth_id="kc-erasure-api-missing-admin",
        email="erasure-api-missing-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    missing_dsr_id = uuid4()
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.post(
        f"/api/v1/platform/privacy/data-subject-requests/"
        f"{missing_dsr_id}/execute-erasure",
        json={},
    )

    assert response.status_code == 404


def test_erasure_execution_api_returns_failed_execution_state(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    subject = _provision_user(
        migrated_session_factory,
        "kc-erasure-api-failed-subject",
        "erasure-api-failed-subject@example.com",
    )
    admin = _provision_platform_actor(
        migrated_session_factory,
        external_auth_id="kc-erasure-api-admin",
        email="erasure-api-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )
    dsr_id = _create_approved_erase_dsr(migrated_session_factory, subject)
    _create_processing_invite_outbox(
        migrated_session_factory,
        subject_email=subject.email,
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.post(
        f"/api/v1/platform/privacy/data-subject-requests/{dsr_id}/execute-erasure",
        json={},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["execution_status"] == DataSubjectRequestExecutionStatus.FAILED.value
    assert body["execution_failure_reason_code"] == (
        "outbox_erasure_processing_rows_in_flight"
    )


def test_erasure_execution_api_rejects_non_erase_request(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
) -> None:
    subject = _provision_user(
        migrated_session_factory,
        "kc-erasure-api-export-subject",
        "erasure-api-export-subject@example.com",
    )
    admin = _provision_platform_actor(
        migrated_session_factory,
        external_auth_id="kc-erasure-api-export-admin",
        email="erasure-api-export-admin@example.com",
        role=PlatformRole.PLATFORM_ADMIN,
    )

    async def _create_export_dsr():
        async with migrated_session_factory() as session:
            async with session.begin():
                dsr = DataSubjectRequest(
                    request_type="export",
                    status=DataSubjectRequestStatus.APPROVED.value,
                    requester_user_id=subject.id,
                    subject_user_id=subject.id,
                    submitted_at=datetime.now(UTC),
                    reviewed_at=datetime.now(UTC),
                    decided_at=datetime.now(UTC),
                    due_at=datetime.now(UTC),
                )
                session.add(dsr)
                await session.flush()
                return dsr.id

    dsr_id = run_async(_create_export_dsr())
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
    )

    response = bundle.client.post(
        f"/api/v1/platform/privacy/data-subject-requests/{dsr_id}/execute-erasure",
        json={},
    )

    assert response.status_code == 409

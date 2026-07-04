from __future__ import annotations

import json
import zipfile
from io import BytesIO
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.core.errors import NotFoundError
from app.platform.models.platform_staff import (
    PlatformStaff,
    PlatformStaffRole,
    PlatformStaffStatus,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestRequesterRole,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStatus
from app.privacy.services.data_subject_requests import DataSubjectRequestService
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User, UserStatus
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


@pytest.fixture(autouse=True)
def isolated_export_storage(monkeypatch: pytest.MonkeyPatch, tmp_path):
    storage_path = tmp_path / "privacy-exports"
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield storage_path
    finally:
        get_settings.cache_clear()


async def _create_user(
    session,
    *,
    email: str | None = None,
    first_name: str = "DSR",
) -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email or f"user-{uuid4()}@example.com",
        email_verified=True,
        first_name=first_name,
        status=UserStatus.ACTIVE.value,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def _staff_record(
    user: User,
    *,
    role: str = PlatformStaffRole.COMPLIANCE_OFFICER.value,
) -> PlatformStaff:
    return PlatformStaff(
        user_id=user.id,
        role=role,
        status=PlatformStaffStatus.ACTIVE.value,
    )


async def _create_verified_representative_request(
    session,
    *,
    request_type: str,
) -> tuple[DataSubjectRequestService, User, User, User, object]:
    requester = await _create_user(
        session,
        email=f"representative-{uuid4()}@example.com",
        first_name="Representative",
    )
    subject = await _create_user(
        session,
        email=f"subject-{uuid4()}@example.com",
        first_name="Subject",
    )
    reviewer = await _create_user(
        session,
        email=f"reviewer-{uuid4()}@example.com",
        first_name="Reviewer",
    )
    service = DataSubjectRequestService(session)
    request = await service.submit_request(
        requester_user_id=requester.id,
        subject_user_id=subject.id,
        request_type=request_type,
        requester_role=DataSubjectRequestRequesterRole.AUTHORISED_REPRESENTATIVE.value,
        representative_relationship="parent",
        representative_authority_note="Authority evidence checked offline.",
        audit_context=AuditContext(actor_user_id=requester.id),
    )
    await service.verify_representative_authority(
        request_id=request.id,
        reviewer_user_id=reviewer.id,
        reason_code="compliance_review",
        audit_context=AuditContext(actor_user_id=reviewer.id),
    )
    approved = await service.approve_request(
        request_id=request.id,
        reviewer_user_id=reviewer.id,
        reason_code="compliance_review",
        audit_context=AuditContext(actor_user_id=reviewer.id),
    )
    return service, requester, subject, reviewer, approved


def _read_export_payload(archive_bytes: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(archive_bytes), mode="r") as archive:
        assert archive.namelist() == ["export.json"]
        return json.loads(archive.read("export.json"))


def test_verified_representative_export_targets_subject_data(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            (
                _,
                requester,
                subject,
                reviewer,
                request,
            ) = await _create_verified_representative_request(
                session,
                request_type="export",
            )
            export_service = ExportArtifactService(session)
            artifact = await export_service.request_export_artifact(
                request_id=request.id,
                requested_by_user_id=reviewer.id,
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )

            assert artifact.requester_user_id == requester.id
            assert artifact.subject_user_id == subject.id

            artifact.status = ExportArtifactStatus.PROCESSING.value
            ready = await export_service.generate_export_artifact(
                artifact=artifact,
                generated_by_user_id=reviewer.id,
            )
            assert ready.storage_key is not None

            payload = _read_export_payload(
                export_service.storage.get_bytes(ready.storage_key)
            )
            encoded_payload = json.dumps(payload, sort_keys=True)
            user_profile = payload["data"]["users.profile"][0]["payload"]
            dsr_record = next(
                item
                for item in payload["data"]["dsr.workflow_records"]
                if item["payload"].get("id") == str(request.id)
            )

            assert payload["subject_user_id"] == str(subject.id)
            assert payload["requester_user_id"] == str(requester.id)
            assert user_profile["id"] == str(subject.id)
            assert user_profile["email"] == subject.email
            assert requester.email not in encoded_payload
            assert dsr_record["payload"]["has_requester"] is True
            assert "requester_user_id" in dsr_record["redacted_fields"]

    run_async(_run())


def test_representative_export_artifact_is_owned_by_requester(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            (
                _,
                requester,
                subject,
                reviewer,
                request,
            ) = await _create_verified_representative_request(
                session,
                request_type="export",
            )
            export_service = ExportArtifactService(session)
            artifact = await export_service.request_export_artifact(
                request_id=request.id,
                requested_by_user_id=reviewer.id,
                audit_context=AuditContext(actor_user_id=reviewer.id),
            )

            owned = await export_service.get_own_export_artifact(
                artifact_id=artifact.id,
                requester_user_id=requester.id,
            )
            with pytest.raises(NotFoundError):
                await export_service.get_own_export_artifact(
                    artifact_id=artifact.id,
                    requester_user_id=subject.id,
                )

            assert owned.id == artifact.id
            assert owned.requester_user_id == requester.id
            assert owned.subject_user_id == subject.id

    run_async(_run())


def test_representative_erasure_executes_against_subject_not_requester(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            (
                service,
                requester,
                subject,
                _,
                request,
            ) = await _create_verified_representative_request(
                session,
                request_type="erase",
            )
            executor = await _create_user(
                session,
                email=f"executor-{uuid4()}@example.com",
                first_name="Executor",
            )
            session.add(_staff_record(executor))
            requester_email = requester.email
            subject_email = subject.email
            await session.flush()

            fulfilled = (
                await service.execute_approved_erasure_request_by_platform_staff(
                    request_id=request.id,
                    executor_user_id=executor.id,
                    audit_context=AuditContext(actor_user_id=executor.id),
                )
            )
            await session.refresh(requester)
            await session.refresh(subject)

            assert fulfilled.status == DataSubjectRequestStatus.FULFILLED.value
            assert fulfilled.execution_status == (
                DataSubjectRequestExecutionStatus.READY.value
            )
            assert requester.email == requester_email
            assert requester.external_auth_id.startswith("kc|")
            assert subject_email is not None
            assert subject.email is None
            assert subject.external_auth_id == f"erased-user:{subject.id}"

    run_async(_run())

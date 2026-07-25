from __future__ import annotations

import json
import zipfile
from datetime import UTC, datetime, timedelta
from io import BytesIO
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStatus
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async
from tests.helpers.privacy_exports import (
    generate_export_artifact_in_committed_phases,
)

pytestmark = [pytest.mark.privacy]


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
    now = datetime.now(UTC)
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
        first_name="Ada",
        last_name="Lovelace",
    )
    session.add(user)
    await session.flush()

    dsr = DataSubjectRequest(
        request_type="export",
        status=DataSubjectRequestStatus.APPROVED.value,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=now,
        due_at=now + timedelta(days=30),
    )
    session.add(dsr)
    await session.flush()
    return user, dsr


def _read_export_payload(archive_bytes: bytes) -> dict[str, object]:
    with zipfile.ZipFile(BytesIO(archive_bytes), mode="r") as archive:
        assert archive.namelist() == ["export.json"]
        return json.loads(archive.read("export.json"))


def test_worker_generated_archive_uses_cross_table_subject_exporter(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_approved_export_dsr(session)
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            ready = await generate_export_artifact_in_committed_phases(
                session,
                artifact=artifact,
                generated_by_user_id=user.id,
            )

            assert ready.status == ExportArtifactStatus.READY.value
            assert ready.storage_key is not None

            archive_bytes = service.storage.get_bytes(ready.storage_key)
            payload = _read_export_payload(archive_bytes)

            assert payload["schema_version"] == "1.0"
            assert payload["data_subject_request_id"] == str(dsr.id)
            assert payload["subject_user_id"] == str(user.id)
            assert payload["request_type"] == "export"
            assert payload["request_status"] == DataSubjectRequestStatus.APPROVED.value
            assert payload["artifact_id"] == str(ready.id)
            assert payload["manifest"]["format"] == "privacy_subject_export"

            data = payload["data"]
            profile_records = data["users.profile"]
            assert len(profile_records) == 1
            profile_payload = profile_records[0]["payload"]
            assert profile_payload["id"] == str(user.id)
            assert profile_payload["email"] == user.email
            assert profile_payload["first_name"] == "Ada"
            assert data["dsr.workflow_records"]
            artifact_records = data["export_artifacts.subject_or_actor_metadata"]
            assert artifact_records == []

            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert (
                persisted.execution_status
                == DataSubjectRequestExecutionStatus.READY.value
            )

    run_async(_run())

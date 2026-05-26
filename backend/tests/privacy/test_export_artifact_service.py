from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.core.errors import ConflictError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStatus
from app.privacy.services.export_artifacts import ExportArtifactService
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


@pytest.fixture(autouse=True)
def isolated_export_storage(monkeypatch, tmp_path):
    storage_path = tmp_path / "privacy-exports"
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield storage_path
    finally:
        get_settings.cache_clear()


def test_request_requires_approved_export_dsr(migrated_session_factory):
    async def _run():
        async with migrated_session_factory() as session:
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email="u@example.com",
                email_verified=True,
            )
            session.add(user)
            await session.flush()
            dsr = DataSubjectRequest(
                request_type="erase",
                status=DataSubjectRequestStatus.SUBMITTED.value,
                requester_user_id=user.id,
                subject_user_id=user.id,
                submitted_at=datetime.now(UTC),
                due_at=datetime.now(UTC),
            )
            session.add(dsr)
            await session.flush()
            service = ExportArtifactService(session)
            with pytest.raises(ConflictError):
                await service.request_export_artifact(
                    request_id=dsr.id,
                    requested_by_user_id=user.id,
                    audit_context=AuditContext(actor_user_id=user.id),
                )

    run_async(_run())


def test_generate_export_artifact_marks_ready(migrated_session_factory):
    async def _run():
        async with migrated_session_factory() as session:
            user = User(
                external_auth_id=f"kc|{uuid4()}",
                email="u2@example.com",
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
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            ready = await service.generate_export_artifact(
                artifact=artifact, generated_by_user_id=user.id
            )
            assert ready.status == ExportArtifactStatus.READY.value
            assert ready.storage_key is not None
            assert ready.filename is not None
            assert ready.content_type == "application/zip"
            assert ready.size_bytes is not None and ready.size_bytes > 0
            assert ready.checksum_sha256 is not None
            assert service.storage.exists(ready.storage_key)

    run_async(_run())

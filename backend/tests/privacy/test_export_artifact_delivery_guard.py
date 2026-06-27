from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.core.errors import ConflictError
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
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
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_STORAGE_PATH", str(storage_path))
    monkeypatch.setenv("PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET", "test-secret")
    get_settings.cache_clear()
    try:
        yield storage_path
    finally:
        get_settings.cache_clear()


async def _create_user_and_dsr(session, *, request_type: str, status: str):
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    dsr = DataSubjectRequest(
        request_type=request_type,
        status=status,
        requester_user_id=user.id,
        subject_user_id=user.id,
        submitted_at=datetime.now(UTC),
        due_at=datetime.now(UTC),
    )
    session.add(dsr)
    await session.flush()
    return user, dsr


def test_confirm_delivery_rejects_dsr_cancelled_after_service_precheck(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_user_and_dsr(
                session,
                request_type="export",
                status=DataSubjectRequestStatus.APPROVED.value,
            )
            service = ExportArtifactService(session)
            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )
            artifact.status = ExportArtifactStatus.READY.value
            artifact.storage_key = f"exports/{artifact.id}/artifact.zip"
            artifact.expires_at = datetime.now(UTC) + timedelta(seconds=60)
            await service.repo.save(artifact)

            original_check = service._ensure_download_dsr_is_still_eligible

            async def cancel_after_precheck(checked_artifact):
                await original_check(checked_artifact)
                dsr.status = DataSubjectRequestStatus.CANCELLED.value
                await service.dsr_repo.save(dsr)

            service._ensure_download_dsr_is_still_eligible = cancel_after_precheck

            with pytest.raises(ConflictError, match="no longer available"):
                await service.confirm_export_delivery(
                    artifact=artifact,
                    audit_context=AuditContext(actor_user_id=user.id),
                )

            persisted_artifact = await service.repo.get_by_id(artifact.id)
            assert persisted_artifact is not None
            assert persisted_artifact.download_count == 0
            assert persisted_artifact.downloaded_at is None

            persisted = await service.dsr_repo.get_by_id(dsr.id)
            assert persisted is not None
            assert persisted.status == DataSubjectRequestStatus.CANCELLED.value
            assert persisted.execution_status != (
                DataSubjectRequestExecutionStatus.DELIVERED.value
            )

    run_async(_run())

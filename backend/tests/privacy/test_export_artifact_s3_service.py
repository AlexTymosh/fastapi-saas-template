from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.core.config.settings import get_settings
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestStatus,
)
from app.privacy.models.export_artifact import ExportArtifactStorageBackend
from app.privacy.services.export_artifacts import ExportArtifactService
from app.privacy.storage.s3 import S3CompatibleStorageAdapter
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


def _configure_s3_export_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRIVACY_EXPORTS__ENABLED", "true")
    monkeypatch.setenv("PRIVACY_EXPORTS__STORAGE_BACKEND", "s3_compatible")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_BUCKET_NAME", "privacy-exports")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_REGION_NAME", "eu-west-2")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_ACCESS_KEY_ID", "access-key")
    monkeypatch.setenv("PRIVACY_EXPORTS__S3_SECRET_ACCESS_KEY", "secret-key")
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def clear_settings_cache():
    try:
        yield
    finally:
        get_settings.cache_clear()


async def _create_approved_export_dsr(session: AsyncSession):
    now = datetime.now(UTC)
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=f"{uuid4()}@example.com",
        email_verified=True,
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


def test_service_builds_configured_s3_storage_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_s3_export_storage(monkeypatch)

    service = ExportArtifactService(cast(AsyncSession, object()))

    assert isinstance(service.storage, S3CompatibleStorageAdapter)


def test_request_export_artifact_records_configured_s3_storage_backend(
    monkeypatch: pytest.MonkeyPatch,
    migrated_session_factory,
) -> None:
    _configure_s3_export_storage(monkeypatch)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            user, dsr = await _create_approved_export_dsr(session)
            service = ExportArtifactService(session)

            artifact = await service.request_export_artifact(
                request_id=dsr.id,
                requested_by_user_id=user.id,
                audit_context=AuditContext(actor_user_id=user.id),
            )

            assert (
                artifact.storage_backend
                == ExportArtifactStorageBackend.S3_COMPATIBLE.value
            )

    run_async(_run())

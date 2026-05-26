from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.core.platform.permissions import PlatformRole
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.privacy.models.data_subject_request import DataSubjectRequest
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
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
    session_factory, external_auth_id: str, email: str, role: PlatformRole
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                await PlatformStaffRepository(session).create_staff(
                    user_id=user.id, role=role.value
                )
            return user

    return run_async(_run())


def _create_export_dsr(session_factory, user):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                dsr = DataSubjectRequest(
                    request_type="export",
                    status="approved",
                    requester_user_id=user.id,
                    subject_user_id=user.id,
                    submitted_at=datetime.now(UTC),
                    due_at=datetime.now(UTC),
                )
                session.add(dsr)
                await session.flush()
                return dsr.id

    return run_async(_run())


def _create_ready_artifact(session_factory, user):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                dsr = DataSubjectRequest(
                    request_type="export",
                    status="approved",
                    requester_user_id=user.id,
                    subject_user_id=user.id,
                    submitted_at=datetime.now(UTC),
                    due_at=datetime.now(UTC),
                )
                session.add(dsr)
                await session.flush()

                artifact = ExportArtifact(
                    data_subject_request_id=dsr.id,
                    requester_user_id=user.id,
                    subject_user_id=user.id,
                    status=ExportArtifactStatus.READY.value,
                    format=ExportArtifactFormat.JSON_ZIP.value,
                    storage_backend=ExportArtifactStorageBackend.LOCAL.value,
                    storage_key=f"exports/{uuid4()}/artifact.zip",
                    filename="privacy-export.zip",
                    content_type="application/zip",
                    size_bytes=123,
                    checksum_sha256="a" * 64,
                    schema_version="1.0",
                    queued_at=datetime.now(UTC),
                    completed_at=datetime.now(UTC),
                    expires_at=datetime.now(UTC) + timedelta(days=30),
                )
                session.add(artifact)
                await session.flush()
                return artifact.id

    return run_async(_run())


def test_unauthenticated_user_cannot_list_export_artifacts(
    client_factory, migrated_database_url
) -> None:
    client = client_factory(database_url=migrated_database_url)
    response = client.get("/api/v1/privacy/export-artifacts")
    assert response.status_code == 401


def test_authenticated_user_can_call_export_artifact_list(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _provision_user(
        migrated_session_factory, "kc-user-export", "export-user@example.com"
    )

    bundle = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/privacy/export-artifacts")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"data", "meta", "links"}


def test_user_cannot_read_or_download_another_users_export_artifact(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    owner = _provision_user(
        migrated_session_factory, "kc-export-owner", "export-owner@example.com"
    )
    stranger = _provision_user(
        migrated_session_factory, "kc-export-stranger", "export-stranger@example.com"
    )
    artifact_id = _create_ready_artifact(migrated_session_factory, owner)

    owner_client = authenticated_client_factory(
        identity=identity_for(owner.external_auth_id, owner.email),
        database_url=migrated_database_url,
    )
    stranger_client = authenticated_client_factory(
        identity=identity_for(stranger.external_auth_id, stranger.email),
        database_url=migrated_database_url,
    )

    owner_detail = owner_client.client.get(
        f"/api/v1/privacy/export-artifacts/{artifact_id}"
    )
    assert owner_detail.status_code == 200
    for forbidden in ("storage_key", "local_path"):
        assert forbidden not in owner_detail.json()

    stranger_detail = stranger_client.client.get(
        f"/api/v1/privacy/export-artifacts/{artifact_id}"
    )
    assert stranger_detail.status_code == 404

    stranger_download = stranger_client.client.post(
        f"/api/v1/privacy/export-artifacts/{artifact_id}/download-url"
    )
    assert stranger_download.status_code == 404


def test_user_can_create_download_url_for_own_ready_artifact(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    user = _provision_user(
        migrated_session_factory, "kc-export-download", "export-download@example.com"
    )
    artifact_id = _create_ready_artifact(migrated_session_factory, user)
    client = authenticated_client_factory(
        identity=identity_for(user.external_auth_id, user.email),
        database_url=migrated_database_url,
    )

    response = client.client.post(
        f"/api/v1/privacy/export-artifacts/{artifact_id}/download-url"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("local://privacy-export/")
    assert body["expires_in_seconds"] > 0


def test_platform_export_artifact_permissions(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    normal = _provision_user(
        migrated_session_factory, "kc-export-normal", "export-normal@example.com"
    )
    support = _provision_platform_actor(
        migrated_session_factory,
        "kc-export-support",
        "export-support@example.com",
        PlatformRole.SUPPORT_AGENT,
    )
    compliance = _provision_platform_actor(
        migrated_session_factory,
        "kc-export-compliance",
        "export-compliance@example.com",
        PlatformRole.COMPLIANCE_OFFICER,
    )
    subject = _provision_user(
        migrated_session_factory, "kc-export-subject", "export-subject@example.com"
    )
    dsr_id = _create_export_dsr(migrated_session_factory, subject)

    normal_client = authenticated_client_factory(
        identity=identity_for(normal.external_auth_id, normal.email),
        database_url=migrated_database_url,
    )
    support_client = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
    )
    compliance_client = authenticated_client_factory(
        identity=identity_for(compliance.external_auth_id, compliance.email),
        database_url=migrated_database_url,
    )

    assert (
        normal_client.client.get(
            "/api/v1/platform/privacy/export-artifacts"
        ).status_code
        == 403
    )
    assert (
        support_client.client.get(
            "/api/v1/platform/privacy/export-artifacts"
        ).status_code
        == 403
    )
    assert (
        support_client.client.post(
            f"/api/v1/platform/privacy/data-subject-requests/{dsr_id}/export-artifact"
        ).status_code
        == 403
    )

    listed = compliance_client.client.get("/api/v1/platform/privacy/export-artifacts")
    assert listed.status_code == 200
    assert set(listed.json().keys()) == {"data", "meta", "links"}

    created = compliance_client.client.post(
        f"/api/v1/platform/privacy/data-subject-requests/{dsr_id}/export-artifact"
    )
    assert created.status_code == 200
    assert created.json()["status"] == ExportArtifactStatus.QUEUED.value

from __future__ import annotations

import inspect

import pytest
from pydantic import SecretStr

from app.core.platform.permissions import (
    ROLE_PERMISSIONS,
    PlatformPermission,
    PlatformRole,
)
from app.privacy.api import platform_export_artifacts as platform_api
from app.privacy.storage.local import LocalStorageAdapter

pytestmark = [pytest.mark.privacy, pytest.mark.security]


def test_platform_export_artifact_read_permission_is_specific() -> None:
    assert (
        PlatformPermission.PRIVACY_EXPORT_ARTIFACTS_READ
        in ROLE_PERMISSIONS[PlatformRole.COMPLIANCE_OFFICER]
    )
    assert (
        PlatformPermission.PRIVACY_EXPORT_ARTIFACTS_READ
        not in ROLE_PERMISSIONS[PlatformRole.SUPPORT_AGENT]
    )


def test_platform_export_artifact_read_routes_use_specific_permission() -> None:
    list_source = inspect.getsource(platform_api.list_platform_export_artifacts)
    detail_source = inspect.getsource(platform_api.get_platform_export_artifact)

    assert "PRIVACY_EXPORT_ARTIFACTS_READ" in list_source
    assert "PRIVACY_EXPORT_ARTIFACTS_READ" in detail_source
    assert "PRIVACY_REQUESTS_READ" not in list_source
    assert "PRIVACY_REQUESTS_READ" not in detail_source


def test_platform_export_artifact_mutating_routes_keep_gdpr_export() -> None:
    create_source = inspect.getsource(platform_api.create_platform_export_artifact)
    download_source = inspect.getsource(
        platform_api.create_platform_export_download_url
    )

    assert "GDPR_EXPORT" in create_source
    assert "GDPR_EXPORT" in download_source
    assert "PRIVACY_EXPORT_ARTIFACTS_READ" not in create_source
    assert "PRIVACY_EXPORT_ARTIFACTS_READ" not in download_source


def test_local_storage_adapter_accepts_secretstr_signing_secret(tmp_path) -> None:
    secret = SecretStr("secret-value-for-local-export-signing")
    storage = LocalStorageAdapter(str(tmp_path), secret)
    key = "exports/example/artifact.zip"

    storage.put_bytes(key, b"payload", "application/zip")
    token = storage.generate_download_url(key, 60)

    assert token.startswith("local://privacy-export/")
    assert storage.verify_download_url(token, expected_key=key)
    assert "secret-value-for-local-export-signing" not in token

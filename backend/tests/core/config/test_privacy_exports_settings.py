from __future__ import annotations

import pytest

from app.core.config.settings import Settings


def _staging_settings_kwargs() -> dict[str, object]:
    return {
        "app": {"environment": "staging"},
        "auth": {
            "enabled": True,
            "issuer_url": "https://idp.example.com",
            "audience": "api",
            "allowed_authorized_parties": ["api-client"],
            "metadata_validation": "fail",
        },
        "rate_limiting": {
            "enforced_by_edge": True,
            "trusted_proxy_cidrs": ["10.0.0.0/8"],
            "edge_assertion_header_name": "X-Rate-Limit-Checked",
            "edge_assertion_secret": "x" * 32,
        },
        "outbox": {"invite_delivery_enabled": False},
        "privacy_exports": {
            "enabled": True,
            "storage_backend": "s3_compatible",
            "s3_region_name": "eu-west-2",
            "s3_bucket_name": "privacy-exports",
        },
    }


def test_disabled_s3_export_storage_backend_is_allowed_before_runtime() -> None:
    settings = Settings(
        privacy_exports={
            "enabled": False,
            "storage_backend": "s3_compatible",
        }
    )

    assert settings.privacy_exports.storage_backend == "s3_compatible"


def test_enabled_s3_export_storage_requires_bucket_and_region() -> None:
    with pytest.raises(
        ValueError,
        match="S3_BUCKET_NAME.*S3_REGION_NAME",
    ):
        Settings(
            privacy_exports={
                "enabled": True,
                "storage_backend": "s3_compatible",
            }
        )


def test_s3_export_access_key_pair_must_be_complete() -> None:
    with pytest.raises(
        ValueError,
        match="S3_ACCESS_KEY_ID.*S3_SECRET_ACCESS_KEY",
    ):
        Settings(
            privacy_exports={
                "enabled": True,
                "storage_backend": "s3_compatible",
                "s3_region_name": "eu-west-2",
                "s3_bucket_name": "privacy-exports",
                "s3_access_key_id": "access-key",
            }
        )


def test_s3_kms_key_requires_kms_encryption_mode() -> None:
    with pytest.raises(ValueError, match="S3_SSE_KMS_KEY_ID"):
        Settings(
            privacy_exports={
                "enabled": True,
                "storage_backend": "s3_compatible",
                "s3_region_name": "eu-west-2",
                "s3_bucket_name": "privacy-exports",
                "s3_sse_kms_key_id": "kms-key",
            }
        )


def test_enabled_local_export_storage_is_rejected_in_staging() -> None:
    kwargs = _staging_settings_kwargs()
    kwargs["privacy_exports"] = {
        "enabled": True,
        "storage_backend": "local",
        "local_signing_secret": "s" * 32,
    }

    with pytest.raises(ValueError, match="STORAGE_BACKEND=s3_compatible"):
        Settings(**kwargs)


def test_enabled_s3_export_storage_is_allowed_in_staging() -> None:
    settings = Settings(**_staging_settings_kwargs())

    assert settings.privacy_exports.storage_backend == "s3_compatible"


def test_default_local_export_signing_secret_is_allowed_when_exports_disabled() -> None:
    kwargs = _staging_settings_kwargs()
    kwargs["privacy_exports"] = {"enabled": False}

    settings = Settings(**kwargs)

    assert settings.privacy_exports.enabled is False

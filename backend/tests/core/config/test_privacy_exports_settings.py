from __future__ import annotations

import pytest

from app.core.config.settings import Settings


def _s3_export_settings(**overrides: object) -> dict[str, object]:
    settings: dict[str, object] = {
        "enabled": True,
        "storage_backend": "s3_compatible",
        "s3_region_name": "eu-west-2",
        "s3_bucket_name": "privacy-exports",
    }
    settings.update(overrides)
    return settings


def _staging_settings_kwargs(*, environment: str = "staging") -> dict[str, object]:
    return {
        "app": {"environment": environment},
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
        "privacy_exports": _s3_export_settings(),
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
        Settings(privacy_exports=_s3_export_settings(s3_access_key_id="access-key"))


@pytest.mark.parametrize(
    "credentials",
    [
        {
            "s3_access_key_id": "access-key",
            "s3_secret_access_key": "   ",
        },
        {
            "s3_access_key_id": "   ",
            "s3_secret_access_key": "secret-key",
        },
    ],
)
def test_s3_export_blank_credential_pair_fails_fast(
    credentials: dict[str, str],
) -> None:
    with pytest.raises(
        ValueError,
        match="S3_ACCESS_KEY_ID.*S3_SECRET_ACCESS_KEY",
    ):
        Settings(privacy_exports=_s3_export_settings(**credentials))


def test_s3_export_blank_credentials_are_treated_as_missing() -> None:
    settings = Settings(
        privacy_exports=_s3_export_settings(
            s3_access_key_id="   ",
            s3_secret_access_key="\t",
        )
    )

    assert settings.privacy_exports.s3_access_key_id is None
    assert settings.privacy_exports.s3_secret_access_key is None


def test_s3_export_credentials_are_trimmed_when_configured() -> None:
    settings = Settings(
        privacy_exports=_s3_export_settings(
            s3_access_key_id="  access-key  ",
            s3_secret_access_key="  secret-key  ",
        )
    )

    assert settings.privacy_exports.s3_access_key_id is not None
    assert settings.privacy_exports.s3_secret_access_key is not None
    assert settings.privacy_exports.s3_access_key_id.get_secret_value() == "access-key"
    assert (
        settings.privacy_exports.s3_secret_access_key.get_secret_value() == "secret-key"
    )


def test_s3_kms_key_requires_kms_encryption_mode() -> None:
    with pytest.raises(ValueError, match="S3_SSE_KMS_KEY_ID"):
        Settings(privacy_exports=_s3_export_settings(s3_sse_kms_key_id="kms-key"))


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


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_protected_s3_export_storage_rejects_plaintext_endpoint(
    environment: str,
) -> None:
    kwargs = _staging_settings_kwargs(environment=environment)
    kwargs["privacy_exports"] = _s3_export_settings(
        s3_endpoint_url="http://minio.internal:9000",
    )

    with pytest.raises(ValueError, match="S3_ENDPOINT_URL.*https"):
        Settings(**kwargs)


def test_staging_s3_export_storage_allows_plaintext_private_network_override() -> None:
    kwargs = _staging_settings_kwargs()
    kwargs["privacy_exports"] = _s3_export_settings(
        s3_endpoint_url="http://minio.internal:9000",
        s3_allow_plaintext_private_network=True,
    )

    settings = Settings(**kwargs)

    assert settings.privacy_exports.s3_endpoint_url == "http://minio.internal:9000"
    assert settings.privacy_exports.s3_allow_plaintext_private_network is True


def test_local_s3_export_storage_allows_plaintext_endpoint_for_dev_adapters() -> None:
    settings = Settings(
        privacy_exports=_s3_export_settings(
            s3_endpoint_url="http://localhost:9000",
        )
    )

    assert settings.privacy_exports.s3_endpoint_url == "http://localhost:9000"


def test_default_local_export_signing_secret_is_allowed_when_exports_disabled() -> None:
    kwargs = _staging_settings_kwargs()
    kwargs["privacy_exports"] = {"enabled": False}

    settings = Settings(**kwargs)

    assert settings.privacy_exports.enabled is False
    assert settings.privacy_exports.local_signing_secret.get_secret_value()


def test_local_export_signing_secret_is_trimmed_and_masked() -> None:
    raw_secret = "local-export-signing-secret"
    settings = Settings(
        privacy_exports={
            "enabled": False,
            "local_signing_secret": f"  {raw_secret}  ",
        }
    )

    assert (
        settings.privacy_exports.local_signing_secret.get_secret_value() == raw_secret
    )
    assert raw_secret not in repr(settings.model_dump())
    assert "**********" in repr(settings.model_dump())


def test_blank_local_export_signing_secret_is_rejected() -> None:
    with pytest.raises(ValueError, match="LOCAL_SIGNING_SECRET"):
        Settings(privacy_exports={"local_signing_secret": "   "})

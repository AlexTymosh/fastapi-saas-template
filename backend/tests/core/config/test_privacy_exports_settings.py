from __future__ import annotations

import pytest

from app.core.config.settings import Settings


def _staging_settings_kwargs(*, local_signing_secret: str) -> dict[str, object]:
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
            "storage_backend": "local",
            "local_signing_secret": local_signing_secret,
        },
    }


def test_unsupported_export_storage_backend_is_rejected_before_runtime() -> None:
    with pytest.raises(
        ValueError, match="PRIVACY_EXPORTS__STORAGE_BACKEND=s3_compatible"
    ):
        Settings(
            privacy_exports={
                "enabled": False,
                "storage_backend": "s3_compatible",
            }
        )


def test_enabled_unsupported_export_storage_backend_is_rejected_before_runtime() -> (
    None
):
    with pytest.raises(
        ValueError, match="PRIVACY_EXPORTS__STORAGE_BACKEND=s3_compatible"
    ):
        Settings(
            privacy_exports={
                "enabled": True,
                "storage_backend": "s3_compatible",
            }
        )


def test_default_local_export_signing_secret_is_rejected_in_staging() -> None:
    with pytest.raises(ValueError, match="PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET"):
        Settings(
            **_staging_settings_kwargs(local_signing_secret="dev-only-signing-secret")
        )


def test_overridden_local_export_signing_secret_is_allowed_in_staging() -> None:
    settings = Settings(**_staging_settings_kwargs(local_signing_secret="s" * 32))

    assert settings.privacy_exports.local_signing_secret == "s" * 32


def test_default_local_export_signing_secret_is_allowed_when_exports_disabled() -> None:
    kwargs = _staging_settings_kwargs(local_signing_secret="dev-only-signing-secret")
    kwargs["privacy_exports"] = {"enabled": False}

    settings = Settings(**kwargs)

    assert settings.privacy_exports.enabled is False

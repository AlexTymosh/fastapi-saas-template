import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]


def _set_complete_prod_base(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main/")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web,fastapi-admin")
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "fail")
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    monkeypatch.setenv(
        "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY",
        "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY=",
    )


def _set_complete_staging_base(monkeypatch) -> None:
    _set_complete_prod_base(monkeypatch)
    monkeypatch.setenv("APP__ENVIRONMENT", "staging")


def test_settings_parse_trusted_proxy_cidrs(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8, 192.168.1.1")

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.trusted_proxy_cidrs == [
        "10.0.0.0/8",
        "192.168.1.1/32",
    ]

    reset_settings_cache()


def test_settings_reject_invalid_trusted_proxy_cidr(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "not-a-cidr")

    reset_settings_cache()
    with pytest.raises(ValueError, match="Invalid trusted proxy CIDR"):
        get_settings()

    reset_settings_cache()


def test_prod_trust_proxy_headers_requires_trusted_proxy_cidrs(monkeypatch) -> None:
    _set_complete_prod_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", "i" * 32)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "true")
    monkeypatch.delenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", raising=False)

    reset_settings_cache()
    with pytest.raises(ValueError, match="RATE_LIMITING__TRUSTED_PROXY_CIDRS"):
        get_settings()

    reset_settings_cache()


def test_prod_app_rate_limiting_requires_pre_auth_unless_verified_edge(
    monkeypatch,
) -> None:
    _set_complete_prod_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", "i" * 32)
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")

    reset_settings_cache()
    with pytest.raises(ValueError, match="RATE_LIMITING__PRE_AUTH_ENABLED"):
        get_settings()

    reset_settings_cache()


def test_staging_requires_app_rate_limiting_or_verified_edge(monkeypatch) -> None:
    _set_complete_staging_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")

    reset_settings_cache()
    with pytest.raises(ValueError, match="Rate limiting must be enabled"):
        get_settings()

    reset_settings_cache()


def test_staging_app_rate_limiting_requires_pre_auth_unless_verified_edge(
    monkeypatch,
) -> None:
    _set_complete_staging_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", "i" * 32)
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")

    reset_settings_cache()
    with pytest.raises(ValueError, match="RATE_LIMITING__PRE_AUTH_ENABLED"):
        get_settings()

    reset_settings_cache()


def test_staging_accepts_app_rate_limiting_with_pre_auth(monkeypatch) -> None:
    _set_complete_staging_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", "i" * 32)
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")

    reset_settings_cache()
    settings = get_settings()

    assert settings.app.environment == "staging"
    assert settings.rate_limiting.enabled is True
    assert settings.rate_limiting.pre_auth_enabled is True

    reset_settings_cache()


def test_prod_edge_enforced_requires_trusted_edge_controls(monkeypatch) -> None:
    _set_complete_prod_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")

    reset_settings_cache()
    with pytest.raises(ValueError, match="trusted edge controls"):
        get_settings()

    reset_settings_cache()


def test_staging_edge_enforced_requires_trusted_edge_controls(monkeypatch) -> None:
    _set_complete_staging_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")

    reset_settings_cache()
    with pytest.raises(ValueError, match="trusted edge controls"):
        get_settings()

    reset_settings_cache()


def test_prod_accepts_verified_edge_enforced_mode(monkeypatch) -> None:
    _set_complete_prod_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.enforced_by_edge is True
    assert settings.rate_limiting.edge_assertion_header_name == "X-Edge-Assertion"
    assert settings.rate_limiting.edge_assertion_secret is not None

    reset_settings_cache()


def test_staging_accepts_verified_edge_enforced_mode(monkeypatch) -> None:
    _set_complete_staging_base(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)

    reset_settings_cache()
    settings = get_settings()

    assert settings.app.environment == "staging"
    assert settings.rate_limiting.enforced_by_edge is True
    assert settings.rate_limiting.edge_assertion_header_name == "X-Edge-Assertion"
    assert settings.rate_limiting.edge_assertion_secret is not None

    reset_settings_cache()

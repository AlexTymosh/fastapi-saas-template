import pytest

from app.core.config.settings import get_settings
from app.core.db.session import _database_url_with_ssl_mode
from tests.helpers.settings import reset_settings_cache

FERNET_TEST_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
RATE_LIMIT_SECRET = "test-rate-limit-identifier-secret-32chars"


def _set_complete_staging_prod_auth(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main/")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web,fastapi-admin")
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "fail")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)


def _set_app_rate_limiting_baseline(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", RATE_LIMIT_SECRET)


def _set_complete_prod_baseline(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_staging_prod_auth(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    _set_app_rate_limiting_baseline(monkeypatch)
    monkeypatch.setenv(
        "DATABASE__URL", "postgresql+psycopg://app:app@db.example:5432/app"
    )
    monkeypatch.setenv("DATABASE__SSL_MODE", "require")
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")
    monkeypatch.setenv("VAULT__ENABLED", "false")


@pytest.mark.security
@pytest.mark.parametrize(
    ("env_name", "policy_name", "env_policy_name"),
    [
        ("staging", "tenant_write", "TENANT_WRITE"),
        ("prod", "invite_accept", "INVITE_ACCEPT"),
    ],
)
def test_staging_prod_reject_sensitive_rate_limit_fail_open_overrides(
    monkeypatch,
    env_name: str,
    policy_name: str,
    env_policy_name: str,
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", env_name)
    _set_complete_staging_prod_auth(monkeypatch)
    if env_name == "prod":
        monkeypatch.setenv("API__DOCS_ENABLED", "false")
        monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
        _set_app_rate_limiting_baseline(monkeypatch)
        monkeypatch.setenv(
            "DATABASE__URL", "postgresql+psycopg://app:app@db.example:5432/app"
        )
        monkeypatch.setenv("DATABASE__SSL_MODE", "require")
    monkeypatch.setenv(f"RATE_LIMITING__POLICIES__{env_policy_name}__FAIL_OPEN", "true")

    reset_settings_cache()
    with pytest.raises(ValueError, match="fail_open=true is not allowed"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_staging_allows_normal_policy_fail_open_override(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "staging")
    _set_complete_staging_prod_auth(monkeypatch)
    monkeypatch.setenv(
        "RATE_LIMITING__POLICIES__AUTHENTICATED_DEFAULT__FAIL_OPEN", "true"
    )

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.policies["authenticated_default"].fail_open is True

    reset_settings_cache()


@pytest.mark.security
def test_prod_rejects_plaintext_database_transport(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv(
        "DATABASE__URL", "postgresql+psycopg://app:app@db.example:5432/app"
    )
    monkeypatch.delenv("DATABASE__SSL_MODE", raising=False)

    reset_settings_cache()
    with pytest.raises(ValueError, match="DATABASE__SSL_MODE"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_prod_accepts_database_sslmode_from_url(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv(
        "DATABASE__URL",
        "postgresql+psycopg://app:app@db.example:5432/app?sslmode=verify-full",
    )
    monkeypatch.delenv("DATABASE__SSL_MODE", raising=False)

    reset_settings_cache()
    settings = get_settings()

    assert settings.database.url is not None
    assert "sslmode=verify-full" in settings.database.url

    reset_settings_cache()


@pytest.mark.security
def test_prod_accepts_database_plaintext_private_network_exception(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv(
        "DATABASE__URL", "postgresql+psycopg://app:app@db.internal:5432/app"
    )
    monkeypatch.delenv("DATABASE__SSL_MODE", raising=False)
    monkeypatch.setenv("DATABASE__ALLOW_PLAINTEXT_PRIVATE_NETWORK", "true")

    reset_settings_cache()
    settings = get_settings()

    assert settings.database.allow_plaintext_private_network is True

    reset_settings_cache()


@pytest.mark.security
def test_prod_rejects_plaintext_redis_transport(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv("REDIS__URL", "redis://redis.example:6379/0")

    reset_settings_cache()
    with pytest.raises(ValueError, match="REDIS__URL"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_prod_accepts_redis_plaintext_private_network_exception(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv("REDIS__URL", "redis://redis.internal:6379/0")
    monkeypatch.setenv("REDIS__ALLOW_PLAINTEXT_PRIVATE_NETWORK", "true")

    reset_settings_cache()
    settings = get_settings()

    assert settings.redis.allow_plaintext_private_network is True

    reset_settings_cache()


@pytest.mark.security
def test_prod_rejects_plaintext_vault_transport_when_enabled(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv("VAULT__ENABLED", "true")
    monkeypatch.setenv("VAULT__ADDR", "http://vault.example:8200")

    reset_settings_cache()
    with pytest.raises(ValueError, match="VAULT__ADDR"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_prod_accepts_https_vault_transport_when_enabled(monkeypatch) -> None:
    _set_complete_prod_baseline(monkeypatch)
    monkeypatch.setenv("VAULT__ENABLED", "true")
    monkeypatch.setenv("VAULT__ADDR", "https://vault.example:8200")

    reset_settings_cache()
    settings = get_settings()

    assert settings.vault.enabled is True
    assert settings.vault.addr.startswith("https://")

    reset_settings_cache()


def test_database_ssl_mode_setting_is_applied_to_engine_url() -> None:
    database_url = _database_url_with_ssl_mode(
        "postgresql+psycopg://app:app@db.example:5432/app",
        "require",
    )

    assert "sslmode=require" in database_url

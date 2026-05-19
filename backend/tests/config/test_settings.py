import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache

FERNET_TEST_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
RATE_LIMIT_SECRET = "test-rate-limit-identifier-secret-32chars"


def _set_complete_prod_auth(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main/")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web,fastapi-admin")
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "fail")


def _set_app_rate_limiting_baseline(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", RATE_LIMIT_SECRET)


def _set_verified_edge_rate_limiting(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)


def test_settings_parses_nested_env(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "test")
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("REQUEST_CONTEXT__HEADER_NAME", "X-Correlation-ID")
    monkeypatch.setenv("VAULT__ENABLED", "true")
    monkeypatch.setenv("DATABASE__URL", "postgresql://localhost/testdb")

    reset_settings_cache()
    settings = get_settings()

    assert settings.app.environment == "test"
    assert settings.logging.as_json is True
    assert settings.request_context.header_name == "X-Correlation-ID"
    assert settings.vault.enabled is True
    assert settings.database.url == "postgresql://localhost/testdb"

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.auth
def test_settings_parse_auth_algorithms_from_csv(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__CLIENT_ID", "fastapi-web")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web, fastapi-admin")

    reset_settings_cache()
    settings = get_settings()

    assert settings.auth.algorithms == "RS256"
    assert settings.auth.audience == "fastapi-api"
    assert settings.auth.client_id == "fastapi-web"
    assert settings.auth.allowed_authorized_parties == ["fastapi-web", "fastapi-admin"]

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.auth
def test_settings_rejects_unsupported_auth_algorithm(monkeypatch) -> None:
    monkeypatch.setenv("AUTH__ALGORITHMS", "RS256,ES256")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ALGORITHMS supports only RS256"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.auth
def test_legacy_security_keycloak_env_vars_are_ignored_for_runtime_auth(
    monkeypatch,
) -> None:
    monkeypatch.setenv("AUTH__ISSUER_URL", "http://auth.example/realms/main")
    monkeypatch.setenv("AUTH__CLIENT_ID", "runtime-client")
    monkeypatch.setenv("SECURITY__KEYCLOAK_SERVER_URL", "http://legacy.example")
    monkeypatch.setenv("SECURITY__KEYCLOAK_REALM", "legacy")
    monkeypatch.setenv("SECURITY__KEYCLOAK_CLIENT_ID", "legacy-client")

    reset_settings_cache()
    settings = get_settings()

    assert settings.auth.issuer_url == "http://auth.example/realms/main"
    assert settings.auth.client_id == "runtime-client"
    assert not hasattr(settings.security, "keycloak_server_url")
    assert not hasattr(settings.security, "keycloak_realm")
    assert not hasattr(settings.security, "keycloak_client_id")

    reset_settings_cache()


@pytest.mark.security
def test_settings_reads_rate_limiting_nested_env(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "custom-prefix")
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("RATE_LIMITING__STORAGE_TIMEOUT_SECONDS", "2.5")

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.enabled is False
    assert settings.rate_limiting.redis_prefix == "custom-prefix"
    assert settings.rate_limiting.trust_proxy_headers is True
    assert settings.rate_limiting.storage_timeout_seconds == 2.5

    reset_settings_cache()


@pytest.mark.security
def test_enabled_rate_limiting_requires_identifier_secret(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.delenv("RATE_LIMITING__IDENTIFIER_SECRET", raising=False)

    reset_settings_cache()
    with pytest.raises(
        ValueError, match="RATE_LIMITING__IDENTIFIER_SECRET is required"
    ):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_rate_limiting_identifier_secret_minimum_length(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", "short")

    reset_settings_cache()
    with pytest.raises(ValueError, match="at least 32 characters"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_rate_limiting_identifier_secret_accepts_secret_value(monkeypatch) -> None:
    secret = "x" * 32
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", secret)

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.identifier_secret is not None
    assert settings.rate_limiting.identifier_secret.get_secret_value() == secret

    reset_settings_cache()


@pytest.mark.security
def test_rate_limiting_identifier_secret_is_redacted_in_model_dump(monkeypatch) -> None:
    secret = "y" * 32
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", secret)

    reset_settings_cache()
    settings = get_settings()

    serialised = repr(settings.model_dump())
    assert secret not in serialised
    assert "**********" in serialised

    reset_settings_cache()


@pytest.mark.security
def test_settings_reads_rate_limit_policy_override(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__POLICIES__TENANT_WRITE__LIMIT", "9")
    monkeypatch.setenv("RATE_LIMITING__POLICIES__TENANT_WRITE__WINDOW_SECONDS", "300")
    monkeypatch.setenv("RATE_LIMITING__POLICIES__TENANT_WRITE__FAIL_OPEN", "true")

    reset_settings_cache()
    settings = get_settings()

    override = settings.rate_limiting.policies["tenant_write"]
    assert override.limit == 9
    assert override.window_seconds == 300
    assert override.fail_open is True

    reset_settings_cache()


@pytest.mark.security
def test_settings_rejects_unknown_rate_limit_policy_override(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__POLICIES__UNKNOWN_POLICY__LIMIT", "10")

    reset_settings_cache()
    with pytest.raises(ValueError, match="Unknown rate limit policy override"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.parametrize(
    ("field", "value"),
    [("LIMIT", "0"), ("WINDOW_SECONDS", "0"), ("WINDOW_SECONDS", "61")],
)
def test_settings_rejects_invalid_rate_limit_override_values(
    monkeypatch, field: str, value: str
) -> None:
    monkeypatch.setenv(f"RATE_LIMITING__POLICIES__TENANT_WRITE__{field}", value)

    reset_settings_cache()
    with pytest.raises(ValueError):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_prod_rejects_relaxed_rate_limit_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_prod_auth(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    _set_app_rate_limiting_baseline(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__MODE", "relaxed")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)

    reset_settings_cache()
    with pytest.raises(ValueError, match="RATE_LIMITING__MODE=relaxed"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_prod_accepts_panic_rate_limit_mode(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_prod_auth(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    _set_app_rate_limiting_baseline(monkeypatch)
    monkeypatch.setenv("RATE_LIMITING__MODE", "panic")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.mode == "panic"

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.auth
def test_prod_requires_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("AUTH__ENABLED", "false")
    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ENABLED"):
        get_settings()


@pytest.mark.security
@pytest.mark.auth
def test_staging_requires_auth_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "staging")
    monkeypatch.setenv("AUTH__ENABLED", "false")
    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ENABLED"):
        get_settings()


@pytest.mark.security
@pytest.mark.auth
@pytest.mark.parametrize(
    ("env_name", "missing_env", "match"),
    [
        ("staging", "AUTH__ISSUER_URL", "AUTH__ISSUER_URL"),
        ("prod", "AUTH__ISSUER_URL", "AUTH__ISSUER_URL"),
        ("staging", "AUTH__AUDIENCE", "AUTH__AUDIENCE"),
        ("prod", "AUTH__AUDIENCE", "AUTH__AUDIENCE"),
        (
            "staging",
            "AUTH__ALLOWED_AUTHORIZED_PARTIES",
            "AUTH__ALLOWED_AUTHORIZED_PARTIES",
        ),
        (
            "prod",
            "AUTH__ALLOWED_AUTHORIZED_PARTIES",
            "AUTH__ALLOWED_AUTHORIZED_PARTIES",
        ),
        ("staging", "AUTH__METADATA_VALIDATION", "AUTH__METADATA_VALIDATION=fail"),
        ("prod", "AUTH__METADATA_VALIDATION", "AUTH__METADATA_VALIDATION=fail"),
    ],
)
def test_staging_prod_require_complete_auth_config(
    monkeypatch, env_name: str, missing_env: str, match: str
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", env_name)
    _set_complete_prod_auth(monkeypatch)
    if missing_env == "AUTH__METADATA_VALIDATION":
        monkeypatch.setenv(missing_env, "warn")
    else:
        monkeypatch.delenv(missing_env, raising=False)
    if env_name == "prod":
        monkeypatch.setenv("API__DOCS_ENABLED", "false")
        monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
        _set_app_rate_limiting_baseline(monkeypatch)

    reset_settings_cache()
    with pytest.raises(ValueError, match=match):
        get_settings()


@pytest.mark.security
@pytest.mark.auth
def test_prod_rejects_non_https_auth_urls(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_prod_auth(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    _set_app_rate_limiting_baseline(monkeypatch)
    monkeypatch.setenv("AUTH__ISSUER_URL", "http://auth.example/realms/main")

    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__ISSUER_URL must use HTTPS"):
        get_settings()

    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main")
    monkeypatch.setenv("AUTH__JWKS_URL", "http://auth.example/jwks")
    reset_settings_cache()
    with pytest.raises(ValueError, match="AUTH__JWKS_URL must use HTTPS"):
        get_settings()


@pytest.mark.security
@pytest.mark.auth
def test_prod_rejects_docs_and_request_id_trust(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_prod_auth(monkeypatch)
    _set_app_rate_limiting_baseline(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "true")
    reset_settings_cache()
    with pytest.raises(ValueError, match="API__DOCS_ENABLED"):
        get_settings()
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "true")
    reset_settings_cache()
    with pytest.raises(ValueError, match="REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID"):
        get_settings()


@pytest.mark.security
def test_prod_rate_limiting_edge_override_and_outbox_key(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_prod_auth(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")
    reset_settings_cache()
    with pytest.raises(ValueError, match="Rate limiting"):
        get_settings()

    _set_verified_edge_rate_limiting(monkeypatch)
    monkeypatch.delenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(ValueError, match="OUTBOX_TOKEN_ENCRYPTION_KEY"):
        get_settings()
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)
    reset_settings_cache()
    settings = get_settings()
    assert settings.app.environment == "prod"
    assert settings.rate_limiting.enforced_by_edge is True

    reset_settings_cache()


@pytest.mark.security
def test_dev_requires_outbox_key_when_invite_delivery_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "dev")
    monkeypatch.setenv("OUTBOX__INVITE_DELIVERY_ENABLED", "true")
    monkeypatch.delenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", raising=False)
    reset_settings_cache()
    with pytest.raises(ValueError, match="OUTBOX_TOKEN_ENCRYPTION_KEY"):
        get_settings()


@pytest.mark.security
def test_settings_rejects_invalid_fernet_key(monkeypatch) -> None:
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", "invalid-key")
    reset_settings_cache()
    with pytest.raises(ValueError, match="valid Fernet key"):
        get_settings()


def test_settings_reads_outbox_recovery_env(monkeypatch) -> None:
    monkeypatch.setenv("OUTBOX__STALE_PROCESSING_TIMEOUT_SECONDS", "120.5")
    monkeypatch.setenv("OUTBOX__RECOVERY_BATCH_SIZE", "75")

    reset_settings_cache()
    settings = get_settings()

    assert settings.outbox.stale_processing_timeout_seconds == 120.5
    assert settings.outbox.recovery_batch_size == 75

    reset_settings_cache()


@pytest.mark.security
def test_default_cors_disabled(monkeypatch) -> None:
    reset_settings_cache()
    settings = get_settings()

    assert settings.cors.enabled is False
    assert settings.cors.allow_origins == []
    assert settings.cors.allow_credentials is False

    reset_settings_cache()


@pytest.mark.security
def test_enabled_cors_requires_origin(monkeypatch) -> None:
    monkeypatch.setenv("CORS__ENABLED", "true")
    monkeypatch.setenv("CORS__ALLOW_ORIGINS", "[]")

    reset_settings_cache()
    with pytest.raises(ValueError, match="CORS__ALLOW_ORIGINS"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_cors_rejects_wildcard_with_credentials(monkeypatch) -> None:
    monkeypatch.setenv("CORS__ENABLED", "true")
    monkeypatch.setenv("CORS__ALLOW_ORIGINS", '["*"]')
    monkeypatch.setenv("CORS__ALLOW_CREDENTIALS", "true")

    reset_settings_cache()
    with pytest.raises(ValueError, match="wildcard origins"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_prod_rejects_cors_wildcard_origin(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    _set_complete_prod_auth(monkeypatch)
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    _set_app_rate_limiting_baseline(monkeypatch)
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)
    monkeypatch.setenv("CORS__ENABLED", "true")
    monkeypatch.setenv("CORS__ALLOW_ORIGINS", '["*"]')

    reset_settings_cache()
    with pytest.raises(ValueError, match="CORS wildcard origins"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
def test_cors_list_normalisation_removes_empty_values(monkeypatch) -> None:
    monkeypatch.setenv("CORS__ENABLED", "true")
    monkeypatch.setenv(
        "CORS__ALLOW_ORIGINS",
        '[" http://localhost:3000 ", "", "  ", "http://localhost:5173"]',
    )
    monkeypatch.setenv("CORS__ALLOW_METHODS", '["GET", " ", "POST"]')
    monkeypatch.setenv("CORS__ALLOW_HEADERS", '[" Authorization ", "", "Content-Type"]')
    monkeypatch.setenv("CORS__EXPOSE_HEADERS", '[" X-Request-ID ", "", "Retry-After"]')

    reset_settings_cache()
    settings = get_settings()

    assert settings.cors.allow_origins == [
        "http://localhost:3000",
        "http://localhost:5173",
    ]
    assert settings.cors.allow_methods == ["GET", "POST"]
    assert settings.cors.allow_headers == ["Authorization", "Content-Type"]
    assert settings.cors.expose_headers == ["X-Request-ID", "Retry-After"]

    reset_settings_cache()

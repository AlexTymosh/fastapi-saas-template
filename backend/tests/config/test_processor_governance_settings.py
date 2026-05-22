import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]

FERNET_TEST_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
RATE_LIMIT_SECRET = "test-rate-limit-identifier-secret-32chars"
EDGE_ASSERTION_SECRET = "test-edge-assertion-secret-32-chars"


def _set_complete_staging_auth(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "staging")
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main/")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web,fastapi-admin")
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "fail")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)


def _set_edge_enforced_rate_limit_baseline(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", EDGE_ASSERTION_SECRET)


def _set_app_rate_limiting_baseline(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", RATE_LIMIT_SECRET)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "127.0.0.1/32")


def _enable_processor_governance(monkeypatch) -> None:
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__ENABLED", "true")
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__REQUIRED", "true")
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION", "uk")


def _set_processor_metadata(
    monkeypatch,
    *,
    name: str,
    purpose: str,
    data_categories: str,
    region: str = "uk",
    country: str = "GB",
    dpa_signed: bool = True,
    restricted_transfer: bool = False,
    transfer_mechanism: str = "not_restricted",
) -> None:
    prefix = f"PROCESSOR_GOVERNANCE__PROCESSORS__{name.upper()}"
    monkeypatch.setenv(f"{prefix}__PURPOSE", purpose)
    monkeypatch.setenv(f"{prefix}__DATA_CATEGORIES", data_categories)
    monkeypatch.setenv(f"{prefix}__REGION", region)
    monkeypatch.setenv(f"{prefix}__COUNTRY", country)
    monkeypatch.setenv(f"{prefix}__DPA_SIGNED", str(dpa_signed).lower())
    monkeypatch.setenv(
        f"{prefix}__RESTRICTED_TRANSFER",
        str(restricted_transfer).lower(),
    )
    monkeypatch.setenv(f"{prefix}__TRANSFER_MECHANISM", transfer_mechanism)


def _set_keycloak_processor(monkeypatch) -> None:
    _set_processor_metadata(
        monkeypatch,
        name="keycloak",
        purpose="identity_and_access_management",
        data_categories="identity_profile, authentication_events",
    )


def test_processor_governance_requires_redis_metadata_when_redis_is_configured(
    monkeypatch,
) -> None:
    _set_complete_staging_auth(monkeypatch)
    _set_edge_enforced_rate_limit_baseline(monkeypatch)
    _enable_processor_governance(monkeypatch)
    _set_keycloak_processor(monkeypatch)
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match="PROCESSOR_GOVERNANCE__PROCESSORS__REDIS",
    ):
        get_settings()

    reset_settings_cache()


def test_processor_governance_accepts_redis_metadata_when_rate_limiting_is_edge_only(
    monkeypatch,
) -> None:
    _set_complete_staging_auth(monkeypatch)
    _set_edge_enforced_rate_limit_baseline(monkeypatch)
    _enable_processor_governance(monkeypatch)
    _set_keycloak_processor(monkeypatch)
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")
    _set_processor_metadata(
        monkeypatch,
        name="redis",
        purpose="cache_rate_limit_storage_and_async_task_broker",
        data_categories="rate_limit_identifiers, healthcheck_metadata",
    )

    reset_settings_cache()
    settings = get_settings()

    assert settings.rate_limiting.enabled is False
    assert settings.rate_limiting.enforced_by_edge is True
    assert "redis" in settings.processor_governance.processors

    reset_settings_cache()


def test_processor_governance_requires_otlp_metadata_when_otlp_export_is_enabled(
    monkeypatch,
) -> None:
    _set_complete_staging_auth(monkeypatch)
    _set_app_rate_limiting_baseline(monkeypatch)
    _enable_processor_governance(monkeypatch)
    _set_keycloak_processor(monkeypatch)
    _set_processor_metadata(
        monkeypatch,
        name="redis",
        purpose="rate_limit_storage",
        data_categories="rate_limit_identifiers",
    )
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.setenv(
        "OBSERVABILITY__OTLP_ENDPOINT",
        "https://otel.example/v1/metrics",
    )

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match="PROCESSOR_GOVERNANCE__PROCESSORS__OTLP",
    ):
        get_settings()

    reset_settings_cache()


def test_processor_governance_rejects_restricted_transfer_without_mechanism(
    monkeypatch,
) -> None:
    _set_complete_staging_auth(monkeypatch)
    _set_edge_enforced_rate_limit_baseline(monkeypatch)
    _enable_processor_governance(monkeypatch)
    _set_keycloak_processor(monkeypatch)
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")
    _set_processor_metadata(
        monkeypatch,
        name="redis",
        purpose="cache_rate_limit_storage_and_async_task_broker",
        data_categories="rate_limit_identifiers, healthcheck_metadata",
        region="us",
        country="US",
        restricted_transfer=True,
        transfer_mechanism="not_restricted",
    )

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match="Restricted processor transfers require an approved transfer mechanism",
    ):
        get_settings()

    reset_settings_cache()

import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache

FERNET_TEST_KEY = "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
RATE_LIMIT_SECRET = "test-rate-limit-identifier-secret-32chars"


def _set_prod_with_processor_governance_enabled(monkeypatch) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__ENABLED", "true")
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", "https://auth.example/realms/main/")
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__ALLOWED_AUTHORIZED_PARTIES", "fastapi-web,fastapi-admin")
    monkeypatch.setenv("AUTH__METADATA_VALIDATION", "fail")
    monkeypatch.setenv("API__DOCS_ENABLED", "false")
    monkeypatch.setenv("REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID", "false")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "false")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__IDENTIFIER_SECRET", RATE_LIMIT_SECRET)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "127.0.0.1/32")
    monkeypatch.setenv("SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY", FERNET_TEST_KEY)


def _set_keycloak_processor_governance(monkeypatch) -> None:
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION", "uk")
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__PURPOSE",
        "identity_provider",
    )
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__DATA_CATEGORIES",
        "account_identifiers,contact_data,auth_claims",
    )
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__REGION", "uk")
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__DPA_SIGNED", "true")
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__TRANSFER_MECHANISM",
        "not_restricted",
    )


def _set_redis_processor_governance(monkeypatch) -> None:
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__redis__PURPOSE",
        "cache_broker_and_rate_limit_storage",
    )
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__redis__DATA_CATEGORIES",
        "rate_limit_identifiers,broker_metadata,healthcheck_metadata",
    )
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__PROCESSORS__redis__REGION", "uk")
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__PROCESSORS__redis__DPA_SIGNED", "true")
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__redis__TRANSFER_MECHANISM",
        "not_restricted",
    )


@pytest.mark.security
@pytest.mark.privacy
def test_prod_requires_keycloak_processor_governance_when_enabled(monkeypatch) -> None:
    _set_prod_with_processor_governance_enabled(monkeypatch)

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match="PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION",
    ):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.privacy
def test_prod_accepts_required_keycloak_processor_governance(monkeypatch) -> None:
    _set_prod_with_processor_governance_enabled(monkeypatch)
    _set_keycloak_processor_governance(monkeypatch)

    reset_settings_cache()
    settings = get_settings()

    processor = settings.processor_governance.processors["keycloak"]
    assert settings.processor_governance.data_residency_region == "uk"
    assert processor.purpose == "identity_provider"
    assert processor.data_categories == [
        "account_identifiers",
        "contact_data",
        "auth_claims",
    ]
    assert processor.region == "uk"
    assert processor.dpa_signed is True

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.privacy
def test_prod_requires_redis_processor_governance_when_redis_url_is_configured(
    monkeypatch,
) -> None:
    _set_prod_with_processor_governance_enabled(monkeypatch)
    _set_keycloak_processor_governance(monkeypatch)
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION", "uk")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match="PROCESSOR_GOVERNANCE__PROCESSORS__REDIS",
    ):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.privacy
def test_prod_accepts_redis_processor_governance_without_app_rate_limiting(
    monkeypatch,
) -> None:
    _set_prod_with_processor_governance_enabled(monkeypatch)
    _set_keycloak_processor_governance(monkeypatch)
    _set_redis_processor_governance(monkeypatch)
    monkeypatch.setenv("PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION", "uk")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)
    monkeypatch.setenv("REDIS__URL", "rediss://redis.example:6379/0")

    reset_settings_cache()
    settings = get_settings()

    assert settings.redis.url == "rediss://redis.example:6379/0"
    assert "redis" in settings.processor_governance.processors
    assert (
        settings.processor_governance.processors["redis"].purpose
        == "cache_broker_and_rate_limit_storage"
    )

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.privacy
def test_prod_rejects_restricted_transfer_without_safeguard(monkeypatch) -> None:
    _set_prod_with_processor_governance_enabled(monkeypatch)
    _set_keycloak_processor_governance(monkeypatch)
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__RESTRICTED_TRANSFER",
        "true",
    )
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__TRANSFER_MECHANISM",
        "not_restricted",
    )

    reset_settings_cache()
    with pytest.raises(ValueError, match="Restricted processor transfers"):
        get_settings()

    reset_settings_cache()


@pytest.mark.security
@pytest.mark.privacy
def test_prod_accepts_restricted_transfer_with_uk_idta(monkeypatch) -> None:
    _set_prod_with_processor_governance_enabled(monkeypatch)
    _set_keycloak_processor_governance(monkeypatch)
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__RESTRICTED_TRANSFER",
        "true",
    )
    monkeypatch.setenv(
        "PROCESSOR_GOVERNANCE__PROCESSORS__keycloak__TRANSFER_MECHANISM",
        "uk_idta",
    )

    reset_settings_cache()
    settings = get_settings()

    assert (
        settings.processor_governance.processors["keycloak"].restricted_transfer is True
    )
    assert (
        settings.processor_governance.processors["keycloak"].transfer_mechanism
        == "uk_idta"
    )

    reset_settings_cache()

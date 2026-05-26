from __future__ import annotations

import ipaddress
import json
from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

_SECURE_DATABASE_SSL_MODES = frozenset({"require", "verify-ca", "verify-full"})
_HTTP_HEADER_NAME_CHARS = frozenset(
    "!#$%&'*+-.^_`|~0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)
_RESTRICTED_TRANSFER_MECHANISMS = frozenset(
    {"adequacy", "uk_idta", "uk_addendum", "bcr", "derogation"}
)
_DEFAULT_LOCAL_EXPORT_SIGNING_SECRET = "dev-only-signing-secret"


def _normalise_string_list(
    value: list[str] | tuple[str, ...] | str | None,
) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError:
                raw_items = value.split(",")
            else:
                raw_items = decoded if isinstance(decoded, list) else [value]
        else:
            raw_items = value.split(",")
    else:
        raw_items = value
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _normalise_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    normalised = value.strip()
    return normalised or None


def _normalise_cidr_list(value: list[str] | tuple[str, ...] | str | None) -> list[str]:
    result: list[str] = []
    for raw_item in _normalise_string_list(value):
        try:
            network = ipaddress.ip_network(raw_item, strict=False)
        except ValueError as exc:
            raise ValueError(f"Invalid trusted proxy CIDR: {raw_item}") from exc
        result.append(str(network))
    return result


def _url_scheme(value: str | None) -> str:
    if not value:
        return ""
    return urlsplit(value).scheme.lower()


def _url_query_value(value: str | None, key: str) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    query = parse_qs(parsed.query)
    for candidate_key, values in query.items():
        if candidate_key.lower() == key.lower() and values:
            normalised = values[-1].strip().lower()
            return normalised or None
    return None


def _is_sqlite_database_url(value: str | None) -> bool:
    return _url_scheme(value).startswith("sqlite")


def _is_secure_database_transport(database: DatabaseSettings) -> bool:
    if not database.url:
        return True

    scheme = _url_scheme(database.url)
    if scheme.startswith("sqlite"):
        return True

    if not scheme.startswith("postgresql"):
        return False

    ssl_mode = database.ssl_mode or _url_query_value(database.url, "sslmode")
    return ssl_mode in _SECURE_DATABASE_SSL_MODES


def _is_secure_redis_transport(redis: RedisSettings) -> bool:
    if not redis.url:
        return True
    return _url_scheme(redis.url) == "rediss"


def _is_secure_vault_transport(vault: VaultSettings) -> bool:
    if not vault.addr:
        return True
    return _url_scheme(vault.addr) == "https"


class AppSettings(BaseModel):
    name: str = "SaaS Template"
    version: str = "0.1.0"
    environment: Literal["local", "dev", "test", "staging", "prod"] = "local"
    debug: bool = False


class ApiSettings(BaseModel):
    v1_prefix: str = "/api/v1"
    docs_enabled: bool = True
    openapi_url: str = "/openapi.json"
    docs_url: str | None = None
    redoc_url: str | None = None
    scalar_path: str = "/scalar"


class LoggingSettings(BaseModel):
    level: str = "INFO"
    as_json: bool = False


class RequestContextSettings(BaseModel):
    header_name: str = "X-Request-ID"
    trust_incoming_request_id: bool = True


class VaultSettings(BaseModel):
    enabled: bool = False
    addr: str = "http://vault:8200"
    namespace: str | None = None
    token: str | None = None
    mount: str = "secret"
    path: str = "fastapi-saas-template"
    auth_method: Literal["token", "approle"] = "token"
    role_id: str | None = None
    secret_id: str | None = None
    fail_fast: bool = False
    tls_required: bool = True
    allow_plaintext_private_network: bool = False


class DatabaseSettings(BaseModel):
    url: str | None = None
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800
    healthcheck_timeout: float = 1.0
    ssl_mode: (
        Literal["disable", "allow", "prefer", "require", "verify-ca", "verify-full"]
        | None
    ) = None
    allow_plaintext_private_network: bool = False
    allow_sqlite_in_prod: bool = False

    @field_validator("ssl_mode", mode="before")
    @classmethod
    def normalise_ssl_mode(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalised = _normalise_optional_string(str(value))
        return normalised.lower() if normalised is not None else None


class RedisSettings(BaseModel):
    url: str | None = None
    healthcheck_timeout: float = 0.5
    tls_required: bool = True
    allow_plaintext_private_network: bool = False


class SecuritySettings(BaseModel):
    outbox_token_encryption_key: str | None = None

    @field_validator("outbox_token_encryption_key")
    @classmethod
    def validate_outbox_token_encryption_key(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            return None
        try:
            Fernet(normalized.encode("utf-8"))
        except Exception as exc:
            raise ValueError(
                "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY must be a valid Fernet key"
            ) from exc
        return normalized

    """
    Security settings that are unrelated to runtime JWT validation.

    Runtime JWT validation configuration is sourced from `auth.*` only.
    """

    keycloak_client_secret: str | None = None


class AuthSettings(BaseModel):
    enabled: bool = False
    issuer_url: str | None = None
    audience: str | None = None
    client_id: str | None = None
    allowed_authorized_parties: Annotated[list[str], NoDecode] = Field(
        default_factory=list
    )
    jwks_url: str | None = None
    algorithms: Literal["RS256"] = "RS256"
    leeway_seconds: int = Field(default=30, ge=0, le=120)
    discovery_cache_ttl_seconds: int = Field(default=300, gt=0)
    jwks_cache_ttl_seconds: int = Field(default=300, gt=0)
    require_kid: bool = True
    require_iat: bool = True
    max_token_lifetime_seconds: int = Field(default=3600, gt=0)
    metadata_validation: Literal["disabled", "warn", "fail"] = "warn"
    jwks_refresh_cooldown_seconds: float = Field(default=30.0, gt=0)
    jwks_refresh_lock_timeout_seconds: float = Field(default=2.0, gt=0)

    @field_validator("algorithms", mode="before")
    @classmethod
    def validate_algorithms(cls, value: str) -> str:
        normalised = str(value).strip().upper()
        if normalised != "RS256":
            raise ValueError("AUTH__ALGORITHMS supports only RS256")
        return "RS256"

    @field_validator("issuer_url", "jwks_url")
    @classmethod
    def normalise_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalised = value.strip().rstrip("/")
        return normalised or None

    @field_validator("audience", "client_id")
    @classmethod
    def normalise_optional_string(cls, value: str | None) -> str | None:
        return _normalise_optional_string(value)

    @field_validator("allowed_authorized_parties", mode="before")
    @classmethod
    def normalise_allowed_authorized_parties(
        cls, value: list[str] | tuple[str, ...] | str | None
    ) -> list[str]:
        return _normalise_string_list(value)


class RateLimitPolicyOverride(BaseModel):
    limit: int | None = Field(default=None, gt=0)
    window_seconds: int | None = Field(default=None, gt=0)
    fail_open: bool | None = None

    @field_validator("window_seconds")
    @classmethod
    def validate_supported_window(cls, value: int | None) -> int | None:
        if value is not None and value not in {60, 300, 3600, 86400}:
            raise ValueError(
                "RATE_LIMITING policy window_seconds must be one of "
                "60, 300, 3600, 86400"
            )
        return value


class RateLimitingSettings(BaseModel):
    enabled: bool = False
    enforced_by_edge: bool = False
    backend: Literal["redis"] = "redis"
    redis_prefix: str = "rate-limit"
    trust_proxy_headers: bool = False
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = Field(default_factory=list)
    pre_auth_enabled: bool = False
    edge_assertion_header_name: str | None = None
    edge_assertion_secret: SecretStr | None = None
    identifier_secret: SecretStr | None = None
    mode: Literal["normal", "strict", "relaxed", "panic"] = "normal"
    policies: dict[str, RateLimitPolicyOverride] = Field(default_factory=dict)
    storage_timeout_seconds: float = Field(default=1.0, gt=0)

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def normalise_trusted_proxy_cidrs(
        cls, value: list[str] | tuple[str, ...] | str | None
    ) -> list[str]:
        return _normalise_cidr_list(value)

    @field_validator("edge_assertion_header_name")
    @classmethod
    def normalise_edge_assertion_header_name(cls, value: str | None) -> str | None:
        normalised = _normalise_optional_string(value)
        if normalised is None:
            return None
        if len(normalised) > 128:
            raise ValueError(
                "RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME must be at most "
                "128 characters"
            )
        if any(char not in _HTTP_HEADER_NAME_CHARS for char in normalised):
            raise ValueError(
                "RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME must be a valid HTTP "
                "header name"
            )
        return normalised

    @field_validator("edge_assertion_secret", "identifier_secret")
    @classmethod
    def validate_secret_minimum_length(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        if not secret:
            return None
        if len(secret) < 32:
            raise ValueError("Rate limit secrets must be at least 32 characters")
        return SecretStr(secret)

    @model_validator(mode="after")
    def validate_identifier_secret_required(self) -> RateLimitingSettings:
        if self.enabled and self.identifier_secret is None:
            raise ValueError(
                "RATE_LIMITING__IDENTIFIER_SECRET is required when "
                "RATE_LIMITING__ENABLED=true"
            )
        return self

    @field_validator("policies")
    @classmethod
    def validate_policy_override_names(
        cls, value: dict[str, RateLimitPolicyOverride]
    ) -> dict[str, RateLimitPolicyOverride]:
        from app.core.rate_limit.registry import get_known_rate_limit_policy_names

        known_names = get_known_rate_limit_policy_names()
        unknown_names = sorted(set(value) - known_names)
        if unknown_names:
            raise ValueError(
                "Unknown rate limit policy override name(s): "
                + ", ".join(unknown_names)
            )
        return value


class OutboxSettings(BaseModel):
    invite_delivery_enabled: bool = True
    stale_processing_timeout_seconds: float = Field(default=300, gt=0)
    recovery_batch_size: int = Field(default=100, gt=0)


class InviteRetentionSettings(BaseModel):
    accepted_days: int = Field(default=30, ge=1)
    expired_days: int = Field(default=30, ge=1)
    revoked_days: int = Field(default=30, ge=1)
    batch_size: int = Field(default=500, gt=0, le=5000)


class AuditSettings(BaseModel):
    network_identifier_secret: SecretStr | None = None
    retention_days: int = Field(default=365, ge=1)
    security_retention_days: int = Field(default=730, ge=1)
    compliance_retention_days: int = Field(default=2555, ge=1)
    anonymisation_batch_size: int = Field(default=500, gt=0, le=5000)

    @field_validator("network_identifier_secret")
    @classmethod
    def validate_network_identifier_secret(
        cls, value: SecretStr | None
    ) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        if not secret:
            return None
        if len(secret) < 32:
            raise ValueError(
                "AUDIT__NETWORK_IDENTIFIER_SECRET must be at least 32 characters"
            )
        return SecretStr(secret)


class CorsSettings(BaseModel):
    enabled: bool = False
    allow_origins: list[str] = Field(default_factory=list)
    allow_methods: list[str] = Field(
        default_factory=lambda: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]
    )
    allow_headers: list[str] = Field(
        default_factory=lambda: ["Authorization", "Content-Type", "X-Request-ID"]
    )
    expose_headers: list[str] = Field(
        default_factory=lambda: ["X-Request-ID", "Retry-After"]
    )
    allow_credentials: bool = False
    max_age: int | None = 600

    @field_validator(
        "allow_origins",
        "allow_methods",
        "allow_headers",
        "expose_headers",
        mode="before",
    )
    @classmethod
    def normalise_string_lists(
        cls, value: list[str] | tuple[str, ...] | str | None
    ) -> list[str]:
        return _normalise_string_list(value)

    @model_validator(mode="after")
    def validate_cors_policy(self) -> CorsSettings:
        if self.enabled and not self.allow_origins:
            raise ValueError("CORS__ALLOW_ORIGINS is required when CORS__ENABLED=true")
        if self.allow_credentials and "*" in self.allow_origins:
            raise ValueError(
                "CORS__ALLOW_CREDENTIALS=true cannot be used with wildcard origins"
            )
        return self


class ObservabilitySettings(BaseModel):
    metrics_enabled: bool = False
    exporter: Literal["none", "otlp"] = "none"
    otlp_endpoint: str | None = None
    service_name: str | None = None
    otlp_timeout_seconds: float = Field(default=2.0, gt=0)
    export_interval_millis: int = Field(default=60_000, gt=0)
    export_timeout_millis: int = Field(default=2_000, gt=0)

    @field_validator("otlp_endpoint")
    @classmethod
    def normalize_otlp_endpoint(cls, value: str | None) -> str | None:
        return _normalise_optional_string(value)

    @field_validator("service_name")
    @classmethod
    def normalize_service_name(cls, value: str | None) -> str | None:
        return _normalise_optional_string(value)

    @model_validator(mode="after")
    def validate_otlp_requirements(self) -> ObservabilitySettings:
        if self.metrics_enabled and self.exporter == "otlp" and not self.otlp_endpoint:
            raise ValueError(
                "OBSERVABILITY__OTLP_ENDPOINT is required when "
                "OBSERVABILITY__METRICS_ENABLED=true and OBSERVABILITY__EXPORTER=otlp"
            )
        return self


class ProcessorSettings(BaseModel):
    """Governance metadata for an external processor/subprocessor."""

    purpose: str
    data_categories: Annotated[list[str], NoDecode] = Field(default_factory=list)
    region: str | None = None
    country: str | None = None
    dpa_signed: bool = False
    restricted_transfer: bool = False
    transfer_mechanism: Literal[
        "not_restricted",
        "adequacy",
        "uk_idta",
        "uk_addendum",
        "bcr",
        "derogation",
    ] = "not_restricted"
    subprocessors: Annotated[list[str], NoDecode] = Field(default_factory=list)

    @field_validator("purpose", "region", "country", mode="before")
    @classmethod
    def normalise_optional_text(cls, value: str | None) -> str | None:
        return _normalise_optional_string(value)

    @field_validator("data_categories", "subprocessors", mode="before")
    @classmethod
    def normalise_processor_lists(
        cls, value: list[str] | tuple[str, ...] | str | None
    ) -> list[str]:
        return _normalise_string_list(value)


class PrivacyExportsSettings(BaseModel):
    enabled: bool = False
    storage_backend: Literal["local", "s3_compatible"] = "local"
    local_storage_path: str = ".local/privacy-exports"
    download_url_ttl_seconds: int = Field(default=900, gt=0)
    artifact_retention_days: int = Field(default=30, ge=1)
    max_artifact_size_bytes: int = Field(default=10_485_760, gt=0)
    schema_version: str = "1.0"
    local_signing_secret: str = _DEFAULT_LOCAL_EXPORT_SIGNING_SECRET


class ProcessorGovernanceSettings(BaseModel):
    """Deployment-time processor and transfer governance guardrail.

    The guardrail is intentionally opt-in for this incremental slice. Existing
    prod/staging settings tests create production Settings objects for unrelated
    security checks; enforcing processor metadata globally would mask those
    more specific validations and make configuration tests brittle. A later
    issue slice can switch this from opt-in to mandatory after deployment docs,
    environment examples, and all prod fixtures are updated consistently.
    """

    enabled: bool = False
    required: bool = True
    data_residency_region: str | None = None
    processors: dict[str, ProcessorSettings] = Field(default_factory=dict)

    @field_validator("data_residency_region")
    @classmethod
    def normalise_data_residency_region(cls, value: str | None) -> str | None:
        return _normalise_optional_string(value)

    @field_validator("processors", mode="before")
    @classmethod
    def normalise_processor_keys(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        return {str(key).strip().lower(): item for key, item in value.items()}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        env_nested_delimiter="__",
    )

    app: AppSettings = Field(default_factory=AppSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)
    request_context: RequestContextSettings = Field(
        default_factory=RequestContextSettings
    )
    vault: VaultSettings = Field(default_factory=VaultSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    redis: RedisSettings = Field(default_factory=RedisSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    rate_limiting: RateLimitingSettings = Field(default_factory=RateLimitingSettings)
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)
    invite_retention: InviteRetentionSettings = Field(
        default_factory=InviteRetentionSettings
    )
    audit: AuditSettings = Field(default_factory=AuditSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    processor_governance: ProcessorGovernanceSettings = Field(
        default_factory=ProcessorGovernanceSettings
    )
    cors: CorsSettings = Field(default_factory=CorsSettings)
    privacy_exports: PrivacyExportsSettings = Field(
        default_factory=PrivacyExportsSettings
    )

    @model_validator(mode="after")
    def validate_environment_security(self) -> Settings:
        env = self.app.environment

        if env in {"staging", "prod"}:
            if not self.auth.enabled:
                raise ValueError("AUTH__ENABLED must be true in staging/prod")
            if not self.auth.issuer_url:
                raise ValueError("AUTH__ISSUER_URL is required in staging/prod")
            if not self.auth.audience:
                raise ValueError("AUTH__AUDIENCE is required in staging/prod")
            if not self.auth.allowed_authorized_parties:
                raise ValueError(
                    "AUTH__ALLOWED_AUTHORIZED_PARTIES is required in staging/prod"
                )
            if self.auth.metadata_validation != "fail":
                raise ValueError(
                    "AUTH__METADATA_VALIDATION=fail is required in staging/prod"
                )

            self._validate_rate_limit_protection_required(env=env)
            self._validate_rate_limit_fail_open_overrides(env=env)
            self._validate_trusted_proxy_header_policy(env=env)
            self._validate_pre_auth_policy(env=env)
            self._validate_edge_enforced_mode(env=env)
            self._validate_processor_governance(env=env)
            self._validate_privacy_exports_security(env=env)

        if env == "prod":
            if not self.auth.issuer_url.startswith("https://"):
                raise ValueError("AUTH__ISSUER_URL must use HTTPS in prod")
            if self.auth.jwks_url and not self.auth.jwks_url.startswith("https://"):
                raise ValueError("AUTH__JWKS_URL must use HTTPS in prod")
            if self.api.docs_enabled:
                raise ValueError("API__DOCS_ENABLED must be false in prod")
            if self.request_context.trust_incoming_request_id:
                raise ValueError(
                    "REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID must be false in prod"
                )
            if self.rate_limiting.mode == "relaxed":
                raise ValueError("RATE_LIMITING__MODE=relaxed is not allowed in prod")

            self._validate_production_transport_security()

        if env == "prod" and "*" in self.cors.allow_origins:
            raise ValueError("CORS wildcard origins are not allowed in prod")

        if (
            self.outbox.invite_delivery_enabled
            and env in {"dev", "staging", "prod"}
            and not self.security.outbox_token_encryption_key
        ):
            raise ValueError(
                "SECURITY__OUTBOX_TOKEN_ENCRYPTION_KEY is required for invite outbox"
            )

        return self

    def _validate_rate_limit_protection_required(self, *, env: str) -> None:
        if not self.rate_limiting.enabled and not self.rate_limiting.enforced_by_edge:
            raise ValueError(
                f"Rate limiting must be enabled in app or enforced by edge in {env}"
            )

    def _validate_rate_limit_fail_open_overrides(self, *, env: str) -> None:
        from app.core.rate_limit.registry import get_rate_limit_policy

        unsafe_overrides = []
        for policy_name, override in self.rate_limiting.policies.items():
            if override.fail_open is not True:
                continue
            policy_spec = get_rate_limit_policy(policy_name)
            if policy_spec.sensitivity in {"sensitive", "critical"}:
                unsafe_overrides.append(policy_name)

        if unsafe_overrides:
            policies = ", ".join(sorted(unsafe_overrides))
            raise ValueError(
                "RATE_LIMITING__POLICIES fail_open=true is not allowed for "
                f"sensitive or critical policies in {env}: {policies}"
            )

    def _validate_trusted_proxy_header_policy(self, *, env: str) -> None:
        if (
            self.rate_limiting.trust_proxy_headers
            and not self.rate_limiting.trusted_proxy_cidrs
        ):
            raise ValueError(
                "RATE_LIMITING__TRUSTED_PROXY_CIDRS is required in "
                f"{env} when RATE_LIMITING__TRUST_PROXY_HEADERS=true"
            )

    def _validate_pre_auth_policy(self, *, env: str) -> None:
        if not self.rate_limiting.enabled or self.rate_limiting.enforced_by_edge:
            return

        if not self.rate_limiting.pre_auth_enabled:
            raise ValueError(
                "RATE_LIMITING__PRE_AUTH_ENABLED must be true in "
                f"{env} unless RATE_LIMITING__ENFORCED_BY_EDGE=true"
            )

        if (
            not self.rate_limiting.trust_proxy_headers
            or not self.rate_limiting.trusted_proxy_cidrs
        ):
            raise ValueError(
                "RATE_LIMITING__TRUST_PROXY_HEADERS=true and "
                "RATE_LIMITING__TRUSTED_PROXY_CIDRS are required in "
                f"{env} when app pre-auth rate limiting is enabled without "
                "RATE_LIMITING__ENFORCED_BY_EDGE=true"
            )

    def _validate_edge_enforced_mode(self, *, env: str) -> None:
        if not self.rate_limiting.enforced_by_edge:
            return
        missing = []
        if not self.rate_limiting.trusted_proxy_cidrs:
            missing.append("RATE_LIMITING__TRUSTED_PROXY_CIDRS")
        if not self.rate_limiting.edge_assertion_header_name:
            missing.append("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME")
        if self.rate_limiting.edge_assertion_secret is None:
            missing.append("RATE_LIMITING__EDGE_ASSERTION_SECRET")
        if missing:
            raise ValueError(
                "RATE_LIMITING__ENFORCED_BY_EDGE=true requires trusted edge "
                f"controls in {env}: " + ", ".join(missing)
            )

    def _validate_processor_governance(self, *, env: str) -> None:
        if not self.processor_governance.enabled:
            return

        required_processors = self._required_processor_names()
        if not required_processors:
            return

        if not self.processor_governance.required:
            raise ValueError(
                "PROCESSOR_GOVERNANCE__REQUIRED=false is not allowed in "
                f"{env} when processor governance is enabled and external "
                "processors are enabled"
            )

        if not self.processor_governance.data_residency_region:
            raise ValueError(
                "PROCESSOR_GOVERNANCE__DATA_RESIDENCY_REGION is required in "
                f"{env} when external processors are enabled"
            )

        processors = self.processor_governance.processors
        missing_processors = sorted(required_processors - set(processors))
        if missing_processors:
            missing_envs = ", ".join(
                f"PROCESSOR_GOVERNANCE__PROCESSORS__{name.upper()}"
                for name in missing_processors
            )
            raise ValueError(
                f"Missing processor governance metadata in {env}: {missing_envs}"
            )

        invalid_processors: list[str] = []
        invalid_transfers: list[str] = []
        for name in sorted(required_processors):
            processor = processors[name]
            missing_fields = []
            if not processor.purpose:
                missing_fields.append("PURPOSE")
            if not processor.data_categories:
                missing_fields.append("DATA_CATEGORIES")
            if not processor.region and not processor.country:
                missing_fields.append("REGION or COUNTRY")
            if not processor.dpa_signed:
                missing_fields.append("DPA_SIGNED")
            if missing_fields:
                invalid_processors.append(f"{name} ({', '.join(missing_fields)})")
            if (
                processor.restricted_transfer
                and processor.transfer_mechanism not in _RESTRICTED_TRANSFER_MECHANISMS
            ):
                invalid_transfers.append(name)

        if invalid_processors:
            raise ValueError(
                "Incomplete processor governance metadata in "
                f"{env}: " + "; ".join(invalid_processors)
            )
        if invalid_transfers:
            raise ValueError(
                "Restricted processor transfers require an approved transfer "
                "mechanism in "
                f"{env}: " + ", ".join(invalid_transfers)
            )

    def _validate_privacy_exports_security(self, *, env: str) -> None:
        if not self.privacy_exports.enabled:
            return
        if self.privacy_exports.storage_backend != "local":
            return

        signing_secret = self.privacy_exports.local_signing_secret.strip()
        if signing_secret == _DEFAULT_LOCAL_EXPORT_SIGNING_SECRET:
            raise ValueError(
                "PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET must be changed in "
                f"{env} when PRIVACY_EXPORTS__STORAGE_BACKEND=local"
            )

        if len(signing_secret) < 32:
            raise ValueError(
                "PRIVACY_EXPORTS__LOCAL_SIGNING_SECRET must be at least "
                "32 characters in staging/prod when "
                "PRIVACY_EXPORTS__STORAGE_BACKEND=local"
            )

    def _required_processor_names(self) -> set[str]:
        required_processors: set[str] = set()
        if self.auth.enabled:
            required_processors.add("keycloak")
        if self.redis.url:
            required_processors.add("redis")
        if self.vault.enabled:
            required_processors.add("vault")
        if self.observability.metrics_enabled and self.observability.exporter == "otlp":
            required_processors.add("otlp")
        return required_processors

    def _validate_production_transport_security(self) -> None:
        if (
            _is_sqlite_database_url(self.database.url)
            and not self.database.allow_sqlite_in_prod
        ):
            raise ValueError(
                "SQLite DATABASE__URL is not allowed in prod unless "
                "DATABASE__ALLOW_SQLITE_IN_PROD=true"
            )

        if (
            not self.database.allow_plaintext_private_network
            and not _is_secure_database_transport(self.database)
        ):
            raise ValueError(
                "DATABASE__SSL_MODE must be one of require, verify-ca, or "
                "verify-full in prod unless "
                "DATABASE__ALLOW_PLAINTEXT_PRIVATE_NETWORK=true"
            )

        if (
            self.redis.url
            and self.redis.tls_required
            and not self.redis.allow_plaintext_private_network
            and not _is_secure_redis_transport(self.redis)
        ):
            raise ValueError(
                "REDIS__URL must use rediss:// in prod unless "
                "REDIS__ALLOW_PLAINTEXT_PRIVATE_NETWORK=true"
            )

        if (
            self.vault.enabled
            and self.vault.tls_required
            and not self.vault.allow_plaintext_private_network
            and not _is_secure_vault_transport(self.vault)
        ):
            raise ValueError(
                "VAULT__ADDR must use https:// in prod unless "
                "VAULT__ALLOW_PLAINTEXT_PRIVATE_NETWORK=true"
            )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

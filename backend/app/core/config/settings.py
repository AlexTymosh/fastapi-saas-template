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
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    cors: CorsSettings = Field(default_factory=CorsSettings)

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

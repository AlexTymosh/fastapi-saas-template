from __future__ import annotations

import json
from functools import lru_cache
from typing import Annotated, Literal

from cryptography.fernet import Fernet
from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


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


class DatabaseSettings(BaseModel):
    url: str | None = None
    echo: bool = False
    pool_size: int = 10
    max_overflow: int = 20
    pool_timeout: int = 30
    pool_recycle: int = 1800
    healthcheck_timeout: float = 1.0


class RedisSettings(BaseModel):
    url: str | None = None
    healthcheck_timeout: float = 0.5


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
        if value is None:
            return None
        normalised = value.strip()
        return normalised or None

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
        if value is not None and value not in {60, 300, 3600}:
            raise ValueError(
                "RATE_LIMITING policy window_seconds must be one of 60, 300, 3600"
            )
        return value


class RateLimitingSettings(BaseModel):
    enabled: bool = False
    enforced_by_edge: bool = False
    backend: Literal["redis"] = "redis"
    redis_prefix: str = "rate-limit"
    trust_proxy_headers: bool = False
    identifier_secret: SecretStr | None = None
    mode: Literal["normal", "strict", "relaxed", "panic"] = "normal"
    policies: dict[str, RateLimitPolicyOverride] = Field(default_factory=dict)
    storage_timeout_seconds: float = Field(default=1.0, gt=0)

    @field_validator("identifier_secret")
    @classmethod
    def validate_identifier_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        if not secret:
            return None
        if len(secret) < 32:
            raise ValueError(
                "RATE_LIMITING__IDENTIFIER_SECRET must be at least 32 characters"
            )
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
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            return None
        return normalized

    @field_validator("service_name")
    @classmethod
    def normalize_service_name(cls, value: str | None) -> str | None:
        if value is None:
            return None

        normalized = value.strip()
        if not normalized:
            return None
        return normalized

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
            if (
                not self.rate_limiting.enabled
                and not self.rate_limiting.enforced_by_edge
            ):
                raise ValueError(
                    "Rate limiting must be enabled in app or enforced by edge in prod"
                )
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

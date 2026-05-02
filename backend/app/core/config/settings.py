from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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


class OutboxSettings(BaseModel):
    token_encryption_key: SecretStr | None = None


class SecuritySettings(BaseModel):
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
    jwks_url: str | None = None
    algorithms: str = "RS256"
    leeway_seconds: int = 30
    discovery_cache_ttl_seconds: int = 300
    jwks_cache_ttl_seconds: int = 300

    @field_validator("algorithms")
    @classmethod
    def validate_algorithms(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized != "RS256":
            raise ValueError("AUTH__ALGORITHMS supports only RS256")
        return "RS256"


class RateLimitingSettings(BaseModel):
    enabled: bool = False
    enforced_by_edge: bool = False
    backend: Literal["redis"] = "redis"
    redis_prefix: str = "rate-limit"
    trust_proxy_headers: bool = False
    default_limit: int = 60
    default_window_seconds: int = 60
    default_fail_open: bool = True
    sensitive_fail_open: bool = False
    storage_timeout_seconds: float = 1.0


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
    outbox: OutboxSettings = Field(default_factory=OutboxSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    rate_limiting: RateLimitingSettings = Field(default_factory=RateLimitingSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


@model_validator(mode="after")
def _validate_env(self: Settings) -> Settings:
    env = self.app.environment
    if env in {"staging", "prod"} and not self.auth.enabled:
        raise ValueError("AUTH__ENABLED must be true for staging/prod")
    if env == "prod":
        if self.api.docs_enabled:
            raise ValueError("API__DOCS_ENABLED must be false in prod")
        if self.request_context.trust_incoming_request_id:
            raise ValueError(
                "REQUEST_CONTEXT__TRUST_INCOMING_REQUEST_ID must be false in prod"
            )
        if not self.rate_limiting.enabled and not self.rate_limiting.enforced_by_edge:
            raise ValueError(
                "Rate limiting must be enabled in app or enforced by edge in prod"
            )
        if self.outbox.token_encryption_key is None:
            raise ValueError("OUTBOX__TOKEN_ENCRYPTION_KEY is required in prod")
    return self


Settings._validate_env = _validate_env

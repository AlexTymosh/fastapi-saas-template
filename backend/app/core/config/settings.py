from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field, field_validator
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


class SecuritySettings(BaseModel):
    keycloak_server_url: str | None = None
    keycloak_realm: str | None = None
    keycloak_client_id: str | None = None
    keycloak_client_secret: str | None = None


class AuthSettings(BaseModel):
    enabled: bool = False
    issuer_url: str | None = None
    audience: str | None = None
    client_id: str | None = None
    jwks_url: str | None = None
    algorithms: list[str] = Field(default_factory=lambda: ["RS256"])
    leeway_seconds: int = 30
    discovery_cache_ttl_seconds: int = 300
    jwks_cache_ttl_seconds: int = 300

    @field_validator("algorithms", mode="before")
    @classmethod
    def _parse_algorithms(cls, value: object) -> list[str]:
        if value is None:
            return ["RS256"]

        if isinstance(value, str):
            parsed = [item.strip() for item in value.split(",") if item.strip()]
            normalized = parsed or ["RS256"]
            cls._validate_supported_algorithms(normalized)
            return normalized

        if isinstance(value, list):
            parsed = [str(item).strip() for item in value if str(item).strip()]
            normalized = parsed or ["RS256"]
            cls._validate_supported_algorithms(normalized)
            return normalized

        raise TypeError("AUTH__ALGORITHMS must be a comma-separated string or list")

    @staticmethod
    def _validate_supported_algorithms(algorithms: list[str]) -> None:
        unsupported = [algorithm for algorithm in algorithms if algorithm != "RS256"]
        if unsupported:
            unsupported_values = ", ".join(sorted(set(unsupported)))
            raise ValueError(
                f"Unsupported AUTH__ALGORITHMS value(s): {unsupported_values}. "
                "Only RS256 is supported."
            )


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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

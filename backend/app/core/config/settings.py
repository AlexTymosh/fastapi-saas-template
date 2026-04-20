from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, Field
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


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()

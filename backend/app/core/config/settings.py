from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PROJECT_NAME: str = "SaaS Template"
    VERSION: str = "0.1.0"
    ENVIRONMENT: str = "dev"

    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False


settings = Settings()

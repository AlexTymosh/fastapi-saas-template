from fastapi import APIRouter

from app.core.config.settings import get_settings
from app.core.secrets import (
    build_secrets_provider,
    get_database_url,
    get_keycloak_client_secret,
    get_redis_url,
)

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/vault-check")
async def vault_check() -> dict[str, bool]:
    settings = get_settings()
    provider = build_secrets_provider(settings)

    return {
        "database_url_loaded": bool(get_database_url(settings, provider)),
        "redis_url_loaded": bool(get_redis_url(settings, provider)),
        "keycloak_client_secret_loaded": bool(
            get_keycloak_client_secret(settings, provider)
        ),
    }

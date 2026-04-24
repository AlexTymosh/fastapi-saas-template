from app.core.config.settings import get_settings


def reset_settings_cache() -> None:
    get_settings.cache_clear()

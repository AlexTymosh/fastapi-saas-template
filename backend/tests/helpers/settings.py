from app.core.config.settings import get_settings


def reset_settings_cache() -> None:
    """Reset cached settings so tests can observe fresh environment values."""
    get_settings.cache_clear()

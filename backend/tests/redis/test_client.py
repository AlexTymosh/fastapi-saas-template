import pytest

from app.core.redis import close_redis, ping_redis
from tests.helpers.asyncio_runner import run_async
from tests.helpers.settings import reset_settings_cache


@pytest.mark.integration
def test_ping_redis_round_trip(monkeypatch, redis_integration_url: str) -> None:
    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    reset_settings_cache()

    async def scenario() -> None:
        try:
            await ping_redis()
        finally:
            await close_redis()
            reset_settings_cache()

    run_async(scenario())

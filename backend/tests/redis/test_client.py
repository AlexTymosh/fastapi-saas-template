import os

import pytest

from app.core.config.settings import get_settings
from app.core.redis import close_redis, ping_redis
from tests.helpers.asyncio_runner import run_async


@pytest.mark.integration
def test_ping_redis_round_trip(monkeypatch) -> None:
    redis_url = os.getenv("TEST_REDIS_URL")
    if not redis_url:
        pytest.skip("TEST_REDIS_URL is not set")

    monkeypatch.setenv("REDIS__URL", redis_url)
    get_settings.cache_clear()

    async def scenario() -> None:
        try:
            await ping_redis()
        finally:
            await close_redis()
            get_settings.cache_clear()

    run_async(scenario())

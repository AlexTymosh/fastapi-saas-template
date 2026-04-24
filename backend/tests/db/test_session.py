import pytest

from app.core.db import dispose_engine, ping_database
from tests.helpers.asyncio_runner import run_async
from tests.helpers.settings import reset_settings_cache


@pytest.mark.integration
def test_ping_database_round_trip(monkeypatch, postgres_integration_url: str) -> None:
    monkeypatch.setenv("DATABASE__URL", postgres_integration_url)
    reset_settings_cache()

    try:
        run_async(ping_database())
    finally:
        run_async(dispose_engine())
        reset_settings_cache()

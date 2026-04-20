import os

import pytest

from app.core.config.settings import get_settings
from app.core.db import dispose_engine, ping_database
from tests.helpers.asyncio_runner import run_async


@pytest.mark.integration
def test_ping_database_round_trip(monkeypatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")

    monkeypatch.setenv("DATABASE__URL", database_url)
    get_settings.cache_clear()

    try:
        run_async(ping_database())
    finally:
        run_async(dispose_engine())
        get_settings.cache_clear()

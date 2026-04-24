import os

import pytest

from app.core.db import dispose_engine, ping_database
from tests.helpers.asyncio_runner import run_async
from tests.helpers.settings import reset_settings_cache


@pytest.mark.integration
def test_ping_database_round_trip(monkeypatch) -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")

    monkeypatch.setenv("DATABASE__URL", database_url)
    reset_settings_cache()

    try:
        run_async(ping_database())
    finally:
        run_async(dispose_engine())
        reset_settings_cache()

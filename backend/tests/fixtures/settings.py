from __future__ import annotations

import pytest

from app.core.config.settings import Settings
from app.core.db import dispose_engine
from app.core.redis import close_redis
from tests.helpers.asyncio_runner import run_async
from tests.helpers.settings import reset_settings_cache


@pytest.fixture(autouse=True)
def reset_runtime_state(monkeypatch, tmp_path):
    monkeypatch.setitem(Settings.model_config, "env_file", str(tmp_path / ".env.test"))
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")

    reset_settings_cache()
    yield
    run_async(close_redis())
    run_async(dispose_engine())
    reset_settings_cache()

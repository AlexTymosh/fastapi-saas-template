from __future__ import annotations

import pytest

from app.core.rate_limit.lifecycle import (
    _build_async_redis_uri,
    _build_grouped_redis_url,
)

pytestmark = [pytest.mark.security]


def test_async_storage_uri_accepts_existing_async_prefix() -> None:
    assert _build_async_redis_uri("async+redis://localhost:6379/0") == (
        "async+redis://localhost:6379/0"
    )


def test_grouped_redis_url_strips_limits_async_prefix() -> None:
    assert _build_grouped_redis_url("async+redis://localhost:6379/0") == (
        "redis://localhost:6379/0"
    )
    assert _build_grouped_redis_url("async+rediss://redis.example:6380/1") == (
        "rediss://redis.example:6380/1"
    )


def test_grouped_redis_url_preserves_regular_redis_urls() -> None:
    assert _build_grouped_redis_url("redis://localhost:6379/0") == (
        "redis://localhost:6379/0"
    )
    assert _build_grouped_redis_url("rediss://redis.example:6380/1") == (
        "rediss://redis.example:6380/1"
    )

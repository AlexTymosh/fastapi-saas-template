from __future__ import annotations

import pytest

from app.core.rate_limit.lifecycle import (
    _build_async_redis_uri,
    _build_grouped_redis_client,
    _build_grouped_redis_url,
    _is_grouped_redis_cluster_url,
    _is_grouped_redis_direct_url,
)

pytestmark = [pytest.mark.security]


def test_async_storage_uri_accepts_existing_async_prefix() -> None:
    assert _build_async_redis_uri("async+redis://localhost:6379/0") == (
        "async+redis://localhost:6379/0"
    )
    assert _build_async_redis_uri("async+redis+cluster://localhost:6379/0") == (
        "async+redis+cluster://localhost:6379/0"
    )


def test_grouped_redis_url_strips_limits_async_prefix() -> None:
    assert _build_grouped_redis_url("async+redis://localhost:6379/0") == (
        "redis://localhost:6379/0"
    )
    assert _build_grouped_redis_url("async+rediss://redis.example:6380/1") == (
        "rediss://redis.example:6380/1"
    )
    assert _build_grouped_redis_url("async+unix:///tmp/redis.sock") == (
        "unix:///tmp/redis.sock"
    )


def test_grouped_redis_url_preserves_regular_redis_urls() -> None:
    assert _build_grouped_redis_url("redis://localhost:6379/0") == (
        "redis://localhost:6379/0"
    )
    assert _build_grouped_redis_url("rediss://redis.example:6380/1") == (
        "rediss://redis.example:6380/1"
    )


def test_grouped_redis_url_normalises_cluster_urls_for_redis_py() -> None:
    assert _build_grouped_redis_url("redis+cluster://localhost:6379/0") == (
        "redis://localhost:6379/0"
    )
    assert _build_grouped_redis_url("rediss+cluster://redis.example:6380/1") == (
        "rediss://redis.example:6380/1"
    )
    assert _build_grouped_redis_url("async+redis+cluster://localhost:6379/0") == (
        "redis://localhost:6379/0"
    )
    assert _build_grouped_redis_url("async+rediss+cluster://redis.example:6380/1") == (
        "rediss://redis.example:6380/1"
    )


@pytest.mark.parametrize(
    "url",
    [
        "redis+cluster://localhost:6379/0",
        "rediss+cluster://redis.example:6380/1",
        "async+redis+cluster://localhost:6379/0",
        "async+rediss+cluster://redis.example:6380/1",
    ],
)
def test_grouped_redis_cluster_url_detection(url: str) -> None:
    assert _is_grouped_redis_cluster_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "redis://localhost:6379/0",
        "rediss://redis.example:6380/1",
        "async+redis://localhost:6379/0",
        "async+rediss://redis.example:6380/1",
    ],
)
def test_grouped_redis_cluster_url_detection_ignores_non_cluster_urls(
    url: str,
) -> None:
    assert _is_grouped_redis_cluster_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "redis://localhost:6379/0",
        "rediss://redis.example:6380/1",
        "unix:///tmp/redis.sock",
        "async+redis://localhost:6379/0",
        "async+rediss://redis.example:6380/1",
        "async+unix:///tmp/redis.sock",
    ],
)
def test_grouped_redis_direct_url_detection_accepts_redis_py_schemes(
    url: str,
) -> None:
    assert _is_grouped_redis_direct_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "redis+sentinel://sentinel.example:26379/0",
        "rediss+sentinel://sentinel.example:26379/0",
        "async+redis+sentinel://sentinel.example:26379/0",
        "redis+unix:///tmp/redis.sock",
    ],
)
def test_grouped_redis_direct_url_detection_rejects_limits_only_schemes(
    url: str,
) -> None:
    assert _is_grouped_redis_direct_url(url) is False


@pytest.mark.parametrize(
    "url",
    [
        "redis+sentinel://sentinel.example:26379/0",
        "rediss+sentinel://sentinel.example:26379/0",
        "async+redis+sentinel://sentinel.example:26379/0",
    ],
)
def test_grouped_redis_client_skips_unsupported_limits_only_schemes(
    url: str,
) -> None:
    assert _build_grouped_redis_client(url) is None


def test_grouped_redis_cluster_client_returns_none_on_redis_cluster_exception(
    monkeypatch,
) -> None:
    from redis.exceptions import RedisClusterException

    def _raise_cluster_exception(*args: object, **kwargs: object) -> object:
        raise RedisClusterException("database must be 0 in cluster mode")

    monkeypatch.setattr(
        "redis.asyncio.cluster.RedisCluster.from_url",
        _raise_cluster_exception,
    )

    assert _build_grouped_redis_client("redis+cluster://localhost:6379/1") is None

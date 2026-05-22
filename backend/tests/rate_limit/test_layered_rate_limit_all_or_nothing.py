from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from limits import RateLimitItemPerMinute
from redis.exceptions import RedisError

from app.core.errors import RateLimiterUnavailableError, TooManyRequestsError
from app.core.rate_limit.dependencies import check_rate_limits_for_buckets
from app.core.rate_limit.grouped_atomic import maybe_get_async_redis_client
from app.core.rate_limit.identifiers import RateLimitBucket
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import (
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    RateLimitPolicy,
)
from app.core.rate_limit.registry import build_effective_policy_registry
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]


@dataclass
class _WindowStats:
    reset_time: float


class _PreflightAwareLimiter:
    def __init__(self, *, test_sequence: list[bool]):
        self.test_sequence = list(test_sequence)
        self.operations: list[tuple[str, str, str]] = []
        self.test_calls: list[tuple[str, str]] = []
        self.hit_calls: list[tuple[str, str]] = []
        self.window_calls: list[tuple[str, str]] = []

    async def test(self, item, namespace: str, key: str) -> bool:
        self.operations.append(("test", namespace, key))
        self.test_calls.append((namespace, key))
        return self.test_sequence.pop(0)

    async def hit(self, item, namespace: str, key: str) -> bool:
        self.operations.append(("hit", namespace, key))
        self.hit_calls.append((namespace, key))
        return True

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        self.operations.append(("stats", namespace, key))
        self.window_calls.append((namespace, key))
        return _WindowStats(reset_time=4_102_444_800.0)


class _FailingRedisClient:
    async def eval(self, *args: object, **kwargs: object) -> list[int]:
        raise RedisError("synthetic grouped redis script failure")


@dataclass
class _RecordingRedisClient:
    result: list[int] = field(default_factory=lambda: [1, 0, 0])
    calls: list[tuple[object, ...]] = field(default_factory=list)

    async def eval(self, *args: object, **kwargs: object) -> list[int]:
        self.calls.append(args)
        return self.result


@dataclass
class _RedisBackedStorage:
    client: object


@dataclass
class _BridgeBackedStorage:
    bridge: object


def _build_request(
    monkeypatch,
    limiter: _PreflightAwareLimiter,
    *,
    storage: object | None = None,
    grouped_redis_client: object | None = None,
):
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "false")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET",
        "test-rate-limit-identifier-secret-32chars",
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    app.state.rate_limit_policy_registry = build_effective_policy_registry(
        app.state.settings
    )
    app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=storage if storage is not None else object(),
        limiter=limiter,
        strategy_name="moving-window",
        grouped_redis_client=grouped_redis_client,
    )
    return SimpleNamespace(
        app=app,
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )


def _organisation_checks():
    return [
        (
            INVITE_CREATE_ORGANISATION_POLICY,
            RateLimitBucket(
                kind="organisation",
                raw_value="organisation:00000000-0000-4000-8000-000000000001",
            ),
        ),
        (
            INVITE_CREATE_ORGANISATION_DAILY_POLICY,
            RateLimitBucket(
                kind="organisation",
                raw_value="organisation:00000000-0000-4000-8000-000000000001",
            ),
        ),
    ]


def _custom_grouped_checks(
    *, fail_open: bool
) -> list[tuple[RateLimitPolicy, RateLimitBucket]]:
    return [
        (
            RateLimitPolicy(
                name="test_grouped_fail_open",
                item=RateLimitItemPerMinute(10),
                fail_open=True,
            ),
            RateLimitBucket(kind="organisation", raw_value="organisation:one"),
        ),
        (
            RateLimitPolicy(
                name="test_grouped_strictest",
                item=RateLimitItemPerMinute(10),
                fail_open=fail_open,
            ),
            RateLimitBucket(kind="organisation", raw_value="organisation:two"),
        ),
    ]


@pytest.mark.anyio
async def test_grouped_bucket_later_denial_does_not_consume_earlier_bucket(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, False])
    request = _build_request(monkeypatch, limiter)

    with pytest.raises(TooManyRequestsError):
        await check_rate_limits_for_buckets(
            request=request,
            checks=_organisation_checks(),
        )

    assert len(limiter.test_calls) == 2
    assert limiter.hit_calls == []
    assert len(limiter.window_calls) == 1
    assert limiter.operations[0][0] == "test"
    assert limiter.operations[1][0] == "test"
    assert limiter.operations[2][0] == "stats"


@pytest.mark.anyio
async def test_grouped_bucket_hits_run_only_after_all_preflight_checks_pass(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    request = _build_request(monkeypatch, limiter)

    await check_rate_limits_for_buckets(
        request=request,
        checks=_organisation_checks(),
    )

    assert len(limiter.test_calls) == 2
    assert len(limiter.hit_calls) == 2
    assert [operation[0] for operation in limiter.operations] == [
        "test",
        "test",
        "hit",
        "hit",
    ]


@pytest.mark.anyio
async def test_runtime_grouped_redis_client_uses_lua_path_and_skips_fallback(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[False, False])
    redis_client = _RecordingRedisClient()
    request = _build_request(
        monkeypatch,
        limiter,
        grouped_redis_client=redis_client,
    )

    await check_rate_limits_for_buckets(
        request=request,
        checks=_organisation_checks(),
    )

    assert len(redis_client.calls) == 1
    assert limiter.operations == []


@pytest.mark.anyio
async def test_grouped_redis_errors_use_strictest_policy_fail_closed(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    request = _build_request(
        monkeypatch,
        limiter,
        storage=_RedisBackedStorage(client=_FailingRedisClient()),
    )

    with pytest.raises(RateLimiterUnavailableError):
        await check_rate_limits_for_buckets(
            request=request,
            checks=_custom_grouped_checks(fail_open=False),
        )

    assert limiter.operations == []


@pytest.mark.anyio
async def test_grouped_redis_errors_fail_open_when_all_grouped_policies_allow_it(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    request = _build_request(
        monkeypatch,
        limiter,
        storage=_RedisBackedStorage(client=_FailingRedisClient()),
    )

    await check_rate_limits_for_buckets(
        request=request,
        checks=_custom_grouped_checks(fail_open=True),
    )

    assert limiter.operations == []


def test_grouped_redis_client_discovery_supports_limits_bridge_shape() -> None:
    redis_client = _RecordingRedisClient()
    storage = _BridgeBackedStorage(bridge=SimpleNamespace(client=redis_client))

    assert maybe_get_async_redis_client(storage) is redis_client

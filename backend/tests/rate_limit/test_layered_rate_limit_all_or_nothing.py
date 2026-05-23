from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from limits import RateLimitItemPerMinute
from redis.exceptions import RedisError

from app.core.errors import RateLimiterUnavailableError, TooManyRequestsError
from app.core.rate_limit.dependencies import check_rate_limits_for_buckets
from app.core.rate_limit.grouped_atomic import (
    GROUPED_FIXED_WINDOW_CONSUME_LUA,
    GROUPED_REDIS_HASH_TAG,
    build_grouped_redis_key,
    is_redis_cluster_fallback_error,
    maybe_get_async_redis_client,
)
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


class _ClusterFallbackRedisClient:
    def __init__(
        self,
        message: str,
        *,
        current_value: int = 0,
        ttl_ms: int = 60_000,
    ) -> None:
        self.message = message
        self.current_value = current_value
        self.ttl_ms = ttl_ms
        self.eval_calls: list[tuple[object, ...]] = []
        self.get_keys: list[str] = []
        self.incr_keys: list[str] = []
        self.pexpire_calls: list[tuple[str, int]] = []

    async def eval(self, *args: object, **kwargs: object) -> list[int]:
        self.eval_calls.append(args)
        raise RedisError(self.message)

    async def get(self, key: str) -> str:
        self.get_keys.append(key)
        return str(self.current_value)

    async def pttl(self, key: str) -> int:
        return self.ttl_ms

    async def incr(self, key: str) -> int:
        self.incr_keys.append(key)
        self.current_value += 1
        return self.current_value

    async def pexpire(self, key: str, ttl_ms: int) -> bool:
        self.pexpire_calls.append((key, ttl_ms))
        return True


class _IncompatibleEvalClient:
    async def eval(self, script: str, *, keys: list[str], args: list[str]) -> list[int]:
        raise AssertionError("incompatible eval client must not be selected")


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


def _sensitive_identifier_checks() -> list[tuple[RateLimitPolicy, RateLimitBucket]]:
    return [
        (
            RateLimitPolicy(
                name="test_grouped_organisation",
                item=RateLimitItemPerMinute(10),
                fail_open=False,
            ),
            RateLimitBucket(
                kind="organisation",
                raw_value="organisation:00000000-0000-4000-8000-0000000000aa",
            ),
        ),
        (
            RateLimitPolicy(
                name="test_grouped_email",
                item=RateLimitItemPerMinute(10),
                fail_open=False,
            ),
            RateLimitBucket(
                kind="organisation_target_email",
                raw_value=(
                    "organisation:00000000-0000-4000-8000-0000000000aa:"
                    "email:patient@example.invalid"
                ),
            ),
        ),
        (
            RateLimitPolicy(
                name="test_grouped_invite_token",
                item=RateLimitItemPerMinute(10),
                fail_open=False,
            ),
            RateLimitBucket(
                kind="invite_token",
                raw_value="raw-invite-token-that-must-not-leak",
            ),
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
async def test_grouped_redis_blocked_result_uses_blocking_bucket_retry_after(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    redis_client = _RecordingRedisClient(result=[0, 2, 1500])
    request = _build_request(
        monkeypatch,
        limiter,
        grouped_redis_client=redis_client,
    )
    decisions: list[tuple[str, str, str]] = []

    def _record_rate_limit_decision(
        *, policy_name: str, result: str, identifier_kind: str
    ) -> None:
        decisions.append((policy_name, result, identifier_kind))

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        _record_rate_limit_decision,
    )

    with pytest.raises(TooManyRequestsError) as exc_info:
        await check_rate_limits_for_buckets(
            request=request,
            checks=_organisation_checks(),
        )

    assert exc_info.value.headers["Retry-After"] == "2"
    assert len(redis_client.calls) == 1
    assert limiter.operations == []
    assert (
        INVITE_CREATE_ORGANISATION_DAILY_POLICY.name,
        "blocked",
        "organisation",
    ) in decisions
    assert (
        INVITE_CREATE_ORGANISATION_POLICY.name,
        "blocked",
        "organisation",
    ) not in decisions


@pytest.mark.anyio
async def test_grouped_redis_eval_args_do_not_contain_raw_identifiers(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True, True])
    redis_client = _RecordingRedisClient()
    request = _build_request(
        monkeypatch,
        limiter,
        grouped_redis_client=redis_client,
    )

    await check_rate_limits_for_buckets(
        request=request,
        checks=_sensitive_identifier_checks(),
    )

    assert len(redis_client.calls) == 1
    eval_call = redis_client.calls[0]
    eval_payload = repr(eval_call)

    for raw_value in (
        "00000000-0000-4000-8000-0000000000aa",
        "patient@example.invalid",
        "example.invalid",
        "raw-invite-token-that-must-not-leak",
    ):
        assert raw_value not in eval_payload

    assert GROUPED_REDIS_HASH_TAG in eval_payload
    assert "rlid:v1:hmac-sha256" in eval_payload
    assert limiter.operations == []


@pytest.mark.parametrize(
    "cluster_error",
    [
        "CROSSSLOT Keys in request don't hash to the same slot",
        "MOVED 3999 127.0.0.1:6381",
        "ASK 3999 127.0.0.1:6381",
        "TRYAGAIN Multiple keys request during rehashing of slot",
        "CLUSTERDOWN Hash slot not served",
    ],
)
@pytest.mark.anyio
async def test_grouped_redis_cluster_errors_fall_back_to_same_key_path(
    monkeypatch,
    cluster_error: str,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    redis_client = _ClusterFallbackRedisClient(cluster_error)
    request = _build_request(
        monkeypatch,
        limiter,
        grouped_redis_client=redis_client,
    )

    await check_rate_limits_for_buckets(
        request=request,
        checks=_organisation_checks(),
    )

    assert len(redis_client.eval_calls) == 1
    assert len(redis_client.get_keys) == 2
    assert len(redis_client.incr_keys) == 2
    assert all(GROUPED_REDIS_HASH_TAG in key for key in redis_client.get_keys)
    assert all(GROUPED_REDIS_HASH_TAG in key for key in redis_client.incr_keys)
    assert limiter.operations == []


@pytest.mark.anyio
async def test_grouped_redis_cluster_fallback_uses_lua_keyspace_when_blocked(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    redis_client = _ClusterFallbackRedisClient(
        "MOVED 3999 127.0.0.1:6381",
        current_value=10,
        ttl_ms=1_500,
    )
    request = _build_request(
        monkeypatch,
        limiter,
        grouped_redis_client=redis_client,
    )

    with pytest.raises(TooManyRequestsError) as exc_info:
        await check_rate_limits_for_buckets(
            request=request,
            checks=_custom_grouped_checks(fail_open=False),
        )

    assert exc_info.value.headers["Retry-After"] == "2"
    assert len(redis_client.eval_calls) == 1
    assert len(redis_client.get_keys) == 1
    assert redis_client.incr_keys == []
    assert GROUPED_REDIS_HASH_TAG in redis_client.get_keys[0]
    assert limiter.operations == []


def test_grouped_redis_cluster_fallback_error_detection() -> None:
    for cluster_error in (
        RedisError("CROSSSLOT Keys in request don't hash to the same slot"),
        RedisError("MOVED 3999 127.0.0.1:6381"),
        RedisError("ASK 3999 127.0.0.1:6381"),
        RedisError("TRYAGAIN Multiple keys request during rehashing of slot"),
        RedisError("CLUSTERDOWN Hash slot not served"),
    ):
        assert is_redis_cluster_fallback_error(cluster_error) is True

    assert (
        is_redis_cluster_fallback_error(
            RedisError("synthetic grouped redis script failure")
        )
        is False
    )


@pytest.mark.anyio
async def test_grouped_redis_errors_use_strictest_policy_fail_closed(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    request = _build_request(
        monkeypatch,
        limiter,
        grouped_redis_client=_FailingRedisClient(),
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
        grouped_redis_client=_FailingRedisClient(),
    )

    await check_rate_limits_for_buckets(
        request=request,
        checks=_custom_grouped_checks(fail_open=True),
    )

    assert limiter.operations == []


@pytest.mark.anyio
async def test_explicit_none_grouped_redis_client_uses_compatibility_fallback(
    monkeypatch,
) -> None:
    limiter = _PreflightAwareLimiter(test_sequence=[True, True])
    request = _build_request(
        monkeypatch,
        limiter,
        storage=_RedisBackedStorage(client=_IncompatibleEvalClient()),
        grouped_redis_client=None,
    )

    await check_rate_limits_for_buckets(
        request=request,
        checks=_organisation_checks(),
    )

    assert [operation[0] for operation in limiter.operations] == [
        "test",
        "test",
        "hit",
        "hit",
    ]


def test_grouped_redis_client_discovery_supports_limits_bridge_shape() -> None:
    redis_client = _RecordingRedisClient()
    storage = _BridgeBackedStorage(bridge=SimpleNamespace(client=redis_client))

    assert maybe_get_async_redis_client(storage) is redis_client


def test_grouped_redis_key_uses_shared_hash_tag_for_cluster_scripts() -> None:
    key = build_grouped_redis_key(
        namespace="test-rl:invite_create_organisation:organisation",
        bucket_key="rlid:v1:hmac-sha256:abc123",
    )

    assert key.startswith(f"{GROUPED_REDIS_HASH_TAG}:")
    assert "rlid:v1:hmac-sha256:abc123" in key


def test_grouped_lua_repairs_missing_ttl_on_blocked_bucket() -> None:
    assert "if ttl_ms < 0 then" in GROUPED_FIXED_WINDOW_CONSUME_LUA
    assert "redis.call('PEXPIRE', KEYS[i], ttl_ms)" in GROUPED_FIXED_WINDOW_CONSUME_LUA

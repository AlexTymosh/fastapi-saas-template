from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.core.errors import TooManyRequestsError
from app.core.rate_limit.dependencies import check_rate_limits_for_buckets
from app.core.rate_limit.identifiers import RateLimitBucket
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import (
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
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


def _build_request(monkeypatch, limiter: _PreflightAwareLimiter):
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
        storage=object(),
        limiter=limiter,
        strategy_name="moving-window",
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

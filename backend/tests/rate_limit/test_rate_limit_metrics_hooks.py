from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from limits import RateLimitItemPerMinute

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import RateLimitPolicy
from app.main import create_app
from tests.helpers.settings import reset_settings_cache


@dataclass
class _WindowStats:
    reset_time: float


class _FakeLimiter:
    def __init__(self, *, allow: bool = True, raise_error: Exception | None = None):
        self.allow = allow
        self.raise_error = raise_error

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        return self.allow

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        return _WindowStats(reset_time=4_102_444_800.0)


async def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
        platform_roles=[],
    )


def _build_client(
    monkeypatch,
    *,
    runtime: RateLimiterRuntime,
    fail_open: bool,
    policy_name: str,
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = runtime

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    probe_policy = RateLimitPolicy(
        name=policy_name,
        item=RateLimitItemPerMinute(1),
        fail_open=fail_open,
    )

    router = APIRouter()

    @router.get(
        "/api/v1/test/rate-limit/protected",
        dependencies=[Depends(rate_limit_dependency(probe_policy))],
    )
    async def _protected_probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)
    app.dependency_overrides[get_authenticated_principal] = _principal
    return TestClient(app)


@pytest.mark.parametrize(
    ("allow", "raise_error", "fail_open", "expected_status", "expected_result"),
    [
        (True, None, False, 200, "allowed"),
        (False, None, False, 429, "blocked"),
        (True, RuntimeError("redis down"), False, 503, "backend_error"),
        (True, RuntimeError("redis down"), True, 200, "fail_open"),
    ],
)
def test_rate_limit_dependency_records_duration_for_all_outcomes(
    monkeypatch,
    allow: bool,
    raise_error: Exception | None,
    fail_open: bool,
    expected_status: int,
    expected_result: str,
) -> None:
    policy_name = "test_probe"
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=_FakeLimiter(allow=allow, raise_error=raise_error),
        strategy_name="moving-window",
    )
    durations: list[dict[str, object]] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs),
    )

    client = _build_client(
        monkeypatch,
        runtime=runtime,
        fail_open=fail_open,
        policy_name=policy_name,
    )
    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == expected_status
    assert len(durations) == 1

    duration_call = durations[0]
    assert duration_call["policy_name"] == policy_name
    assert duration_call["result"] == expected_result
    assert duration_call["identifier_kind"] == "user"
    assert isinstance(duration_call["duration_seconds"], float)
    assert duration_call["duration_seconds"] >= 0.0

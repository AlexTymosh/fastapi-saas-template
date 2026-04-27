from __future__ import annotations

from dataclasses import dataclass

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


class FakeLimiter:
    def __init__(self, *, allow: bool = True, raise_error: Exception | None = None):
        self.allow = allow
        self.raise_error = raise_error

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        return self.allow

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        return _WindowStats(reset_time=4_102_444_800.0)


async def _principal_user() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
        platform_roles=[],
    )


def _build_app(
    monkeypatch, *, policy: RateLimitPolicy, runtime: RateLimiterRuntime
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = runtime

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    router = APIRouter()

    @router.get(
        "/api/v1/test/rate-limit/protected",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _protected_probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)
    client = TestClient(app)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user
    return client


def test_rate_limit_allowed_records_allowed_metrics(monkeypatch) -> None:
    decisions: list[str] = []
    durations: list[str] = []
    backend_errors: list[str] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        lambda **kwargs: decisions.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_backend_error",
        lambda **kwargs: backend_errors.append(kwargs["error_type"]),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=True),
        strategy_name="moving-window",
    )
    policy = RateLimitPolicy(
        name="test_allow", item=RateLimitItemPerMinute(1), fail_open=False
    )
    with _build_app(monkeypatch, policy=policy, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 200
    assert decisions == ["allowed"]
    assert durations == ["allowed"]
    assert backend_errors == []


def test_rate_limit_blocked_records_blocked_metrics(monkeypatch) -> None:
    decisions: list[str] = []
    durations: list[str] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        lambda **kwargs: decisions.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs["result"]),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    policy = RateLimitPolicy(
        name="test_block", item=RateLimitItemPerMinute(1), fail_open=False
    )
    with _build_app(monkeypatch, policy=policy, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 429
    assert decisions == ["blocked"]
    assert durations == ["blocked"]


def test_rate_limit_backend_error_fail_closed_records_backend_error(
    monkeypatch,
) -> None:
    decisions: list[str] = []
    durations: list[str] = []
    backend_errors: list[str] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        lambda **kwargs: decisions.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_backend_error",
        lambda **kwargs: backend_errors.append(kwargs["error_type"]),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    policy = RateLimitPolicy(
        name="test_closed", item=RateLimitItemPerMinute(1), fail_open=False
    )
    with _build_app(monkeypatch, policy=policy, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert decisions == ["backend_error"]
    assert durations == ["backend_error"]
    assert backend_errors == ["RuntimeError"]


def test_rate_limit_backend_error_fail_open_records_fail_open(monkeypatch) -> None:
    decisions: list[str] = []
    durations: list[str] = []
    backend_errors: list[str] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        lambda **kwargs: decisions.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs["result"]),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_backend_error",
        lambda **kwargs: backend_errors.append(kwargs["error_type"]),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    policy = RateLimitPolicy(
        name="test_open", item=RateLimitItemPerMinute(1), fail_open=True
    )
    with _build_app(monkeypatch, policy=policy, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 200
    assert decisions == ["fail_open"]
    assert durations == ["fail_open"]
    assert backend_errors == ["RuntimeError"]

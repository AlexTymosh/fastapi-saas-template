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
    monkeypatch,
    *,
    runtime: RateLimiterRuntime,
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = runtime

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    fail_closed_policy = RateLimitPolicy(
        name="test_probe",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )
    fail_open_policy = RateLimitPolicy(
        name="test_fail_open",
        item=RateLimitItemPerMinute(1),
        fail_open=True,
    )

    router = APIRouter()

    @router.get(
        "/api/v1/test/rate-limit/protected",
        dependencies=[Depends(rate_limit_dependency(fail_closed_policy))],
    )
    async def _protected_probe() -> dict[str, str]:
        return {"ok": "true"}

    @router.get(
        "/api/v1/test/rate-limit/fail-open",
        dependencies=[Depends(rate_limit_dependency(fail_open_policy))],
    )
    async def _fail_open_probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)
    app.dependency_overrides[get_authenticated_principal] = _principal_user
    return TestClient(app)


def test_allowed_request_records_duration_with_allowed_result(monkeypatch) -> None:
    durations: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=True),
        strategy_name="moving-window",
    )
    with _build_app(monkeypatch, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 200
    assert len(durations) == 1
    assert durations[0]["policy_name"] == "test_probe"
    assert durations[0]["result"] == "allowed"
    assert durations[0]["identifier_kind"] == "user"
    assert isinstance(durations[0]["duration_seconds"], float)
    assert durations[0]["duration_seconds"] >= 0


def test_blocked_request_records_duration_with_blocked_result(monkeypatch) -> None:
    durations: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    with _build_app(monkeypatch, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 429
    assert len(durations) == 1
    assert durations[0]["policy_name"] == "test_probe"
    assert durations[0]["result"] == "blocked"
    assert durations[0]["identifier_kind"] == "user"
    assert isinstance(durations[0]["duration_seconds"], float)
    assert durations[0]["duration_seconds"] >= 0


def test_fail_closed_backend_error_records_duration_with_backend_error_result(
    monkeypatch,
) -> None:
    durations: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    with _build_app(monkeypatch, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert len(durations) == 1
    assert durations[0]["policy_name"] == "test_probe"
    assert durations[0]["result"] == "backend_error"
    assert durations[0]["identifier_kind"] == "user"
    assert isinstance(durations[0]["duration_seconds"], float)
    assert durations[0]["duration_seconds"] >= 0


def test_fail_open_backend_error_records_duration_with_fail_open_result(
    monkeypatch,
) -> None:
    durations: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs),
    )

    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    with _build_app(monkeypatch, runtime=runtime) as client:
        response = client.get("/api/v1/test/rate-limit/fail-open")

    assert response.status_code == 200
    assert len(durations) == 1
    assert durations[0]["policy_name"] == "test_fail_open"
    assert durations[0]["result"] == "fail_open"
    assert durations[0]["identifier_kind"] == "user"
    assert isinstance(durations[0]["duration_seconds"], float)
    assert durations[0]["duration_seconds"] >= 0

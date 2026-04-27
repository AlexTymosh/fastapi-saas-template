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
    def __init__(self, *, allow: bool = True, error: Exception | None = None) -> None:
        self.allow = allow
        self.error = error

    async def hit(self, item, namespace: str, key: str) -> bool:
        _ = (item, namespace, key)
        if self.error is not None:
            raise self.error
        return self.allow

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        _ = (item, namespace, key)
        return _WindowStats(reset_time=4_102_444_800.0)


async def _principal_user() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
        platform_roles=[],
    )


def _build_client(
    monkeypatch: pytest.MonkeyPatch,
    *,
    limiter: _FakeLimiter,
    policy: RateLimitPolicy,
    route_path: str,
) -> TestClient:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=limiter,
        strategy_name="moving-window",
    )

    async def _fake_init_rate_limiter(app, settings) -> None:
        _ = settings
        app.state.rate_limiter_runtime = runtime

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    router = APIRouter()

    @router.get(route_path, dependencies=[Depends(rate_limit_dependency(policy))])
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)
    app.dependency_overrides[get_authenticated_principal] = _principal_user
    return TestClient(app)


@pytest.mark.parametrize(
    ("case", "allow", "error", "fail_open", "expected_status", "expected_result"),
    [
        ("allowed", True, None, False, 200, "allowed"),
        ("blocked", False, None, False, 429, "blocked"),
        (
            "backend_error",
            True,
            RuntimeError("redis down"),
            False,
            503,
            "backend_error",
        ),
        ("fail_open", True, RuntimeError("redis down"), True, 200, "fail_open"),
    ],
)
def test_rate_limit_duration_hook_records_all_outcomes(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    allow: bool,
    error: Exception | None,
    fail_open: bool,
    expected_status: int,
    expected_result: str,
) -> None:
    _ = case
    durations: list[dict[str, object]] = []
    decisions: list[str] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_request",
        lambda **kwargs: decisions.append(str(kwargs["result"])),
    )

    policy = RateLimitPolicy(
        name="test_probe",
        item=RateLimitItemPerMinute(1),
        fail_open=fail_open,
    )

    with _build_client(
        monkeypatch,
        limiter=_FakeLimiter(allow=allow, error=error),
        policy=policy,
        route_path=f"/api/v1/test/rate-limit/{expected_result}",
    ) as client:
        response = client.get(f"/api/v1/test/rate-limit/{expected_result}")

    assert response.status_code == expected_status
    assert decisions == [expected_result]
    assert len(durations) == 1

    duration_event = durations[0]
    assert duration_event["policy_name"] == "test_probe"
    assert duration_event["result"] == expected_result
    assert duration_event["identifier_kind"] == "user"
    assert isinstance(duration_event["duration_seconds"], float)
    assert duration_event["duration_seconds"] >= 0.0


@pytest.mark.parametrize(
    ("fail_open", "expected_status", "expected_result"),
    [
        (False, 503, "backend_error"),
        (True, 200, "fail_open"),
    ],
)
def test_rate_limit_backend_error_duration_result_depends_on_policy(
    monkeypatch: pytest.MonkeyPatch,
    fail_open: bool,
    expected_status: int,
    expected_result: str,
) -> None:
    durations: list[str] = []

    monkeypatch.setattr(
        "app.core.rate_limit.dependencies.record_rate_limit_check_duration",
        lambda **kwargs: durations.append(str(kwargs["result"])),
    )

    policy = RateLimitPolicy(
        name="test_backend_error",
        item=RateLimitItemPerMinute(1),
        fail_open=fail_open,
    )

    with _build_client(
        monkeypatch,
        limiter=_FakeLimiter(error=RuntimeError("redis down")),
        policy=policy,
        route_path="/api/v1/test/rate-limit/backend-error-check",
    ) as client:
        response = client.get("/api/v1/test/rate-limit/backend-error-check")

    assert response.status_code == expected_status
    assert durations == [expected_result]

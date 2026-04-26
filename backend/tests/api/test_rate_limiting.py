from __future__ import annotations

import inspect
from dataclasses import dataclass

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    RateLimitPolicy,
)
from app.main import create_app
from tests.helpers.settings import reset_settings_cache


@dataclass
class _WindowStats:
    reset_time: float


class FakeLimiter:
    def __init__(self, *, allow: bool = True, raise_error: Exception | None = None):
        self.allow = allow
        self.raise_error = raise_error
        self.hit_calls: list[tuple[str, str, int, int]] = []
        self.window_calls: list[tuple[str, str, int, int]] = []

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        self.hit_calls.append((namespace, key, item.amount, item.multiples))
        return self.allow

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        self.window_calls.append((namespace, key, item.amount, item.multiples))
        return _WindowStats(reset_time=4_102_444_800.0)


async def _principal_user_a() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
        platform_roles=[],
    )


async def _principal_user_b() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-b",
        email="user-b@example.com",
        email_verified=True,
        platform_roles=[],
    )


def _build_client(monkeypatch, *, enabled: bool = True) -> TestClient:
    async def _noop_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=False,
            storage=None,
            limiter=None,
            strategy_name=None,
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _noop_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()
    return TestClient(create_app())


def test_rate_limiting_disabled_is_noop(monkeypatch) -> None:
    client = _build_client(monkeypatch, enabled=False)
    try:
        with client as api_client:
            response = api_client.post(
                "/api/v1/invites/accept",
                json={"token": "invalid-token"},
            )
        assert response.status_code != 429
    finally:
        client.close()


def test_over_limit_returns_429_problem_with_retry_after(monkeypatch) -> None:
    client = _build_client(monkeypatch, enabled=True)
    fake = FakeLimiter(allow=False)

    client.app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.post(
            "/api/v1/invites/accept",
            json={"token": "invalid-token"},
        )

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert response.headers["access-control-expose-headers"] == "Retry-After"


def test_rate_limiter_failure_fail_closed_returns_503(monkeypatch) -> None:
    client = _build_client(monkeypatch, enabled=True)
    fake = FakeLimiter(raise_error=RuntimeError("redis down"))

    client.app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.post(
            "/api/v1/invites/accept",
            json={"token": "invalid-token"},
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_rate_limiter_failure_fail_open_allows_request(monkeypatch) -> None:
    async def _noop_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=True,
            storage=object(),
            limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
            strategy_name="moving-window",
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _noop_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    reset_settings_cache()

    app = create_app()
    app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    policy = RateLimitPolicy(
        name="test_fail_open",
        limit=1,
        window_seconds=60,
        fail_open=True,
    )
    router = APIRouter()

    @router.get(
        "/api/v1/rate-limit-fail-open",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)

    with TestClient(app) as client:
        response = client.get("/api/v1/rate-limit-fail-open")

    assert response.status_code == 200


def test_authenticated_users_have_independent_buckets(monkeypatch) -> None:
    client = _build_client(monkeypatch, enabled=True)
    fake = FakeLimiter(allow=True)
    client.app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )

    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    with client as api_client:
        api_client.post("/api/v1/invites/accept", json={"token": "invalid-token"})

    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_b
    with client as api_client:
        api_client.post("/api/v1/invites/accept", json={"token": "invalid-token"})

    assert len(fake.hit_calls) == 2
    _, first_key, *_ = fake.hit_calls[0]
    _, second_key, *_ = fake.hit_calls[1]
    assert first_key != second_key


def test_invite_policies_are_distinct_and_declarative() -> None:
    assert INVITE_ACCEPT_POLICY.name == "invite_accept"
    assert INVITE_ACCEPT_POLICY.limit == 5
    assert INVITE_ACCEPT_POLICY.window_seconds == 300
    assert INVITE_ACCEPT_POLICY.fail_open is False

    assert INVITE_CREATE_POLICY.name == "invite_create"
    assert INVITE_CREATE_POLICY.limit == 20
    assert INVITE_CREATE_POLICY.window_seconds == 3600
    assert INVITE_CREATE_POLICY.fail_open is False


def test_health_endpoints_are_not_rate_limited(monkeypatch) -> None:
    client = _build_client(monkeypatch, enabled=True)
    client.app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    with client as api_client:
        response = api_client.get("/api/v1/health/live")
    assert response.status_code == 200


def test_runtime_code_uses_limits_aio_namespace() -> None:
    from app.core.rate_limit import dependencies, lifecycle

    dependency_source = inspect.getsource(dependencies)
    lifecycle_source = inspect.getsource(lifecycle)

    assert "limits.aio" in dependency_source or "limits.aio" in lifecycle_source

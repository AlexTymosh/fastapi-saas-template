from __future__ import annotations

import inspect
from dataclasses import dataclass
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock

from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from limits import RateLimitItemPerMinute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_authenticated_principal,
)
from app.core.db.session import get_db_session
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


def _build_app(
    monkeypatch,
    *,
    enabled: bool,
    runtime: RateLimiterRuntime | None = None,
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = runtime or RateLimiterRuntime(
            enabled=False,
            storage=None,
            limiter=None,
            strategy_name=None,
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    probe_policy = RateLimitPolicy(
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
        dependencies=[Depends(rate_limit_dependency(probe_policy))],
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
    return TestClient(app)


def test_default_test_configuration_does_not_start_rate_limiter(monkeypatch) -> None:
    with _build_app(monkeypatch, enabled=False) as client:
        runtime = client.app.state.rate_limiter_runtime

    assert runtime.enabled is False
    assert runtime.storage is None
    assert runtime.limiter is None


def test_rate_limiting_disabled_is_noop(monkeypatch) -> None:
    with _build_app(monkeypatch, enabled=False) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 401


def test_over_limit_returns_429_problem_with_retry_after(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert response.headers["access-control-expose-headers"] == "Retry-After"


def test_rate_limiter_failure_fail_closed_returns_503(monkeypatch) -> None:
    fake = FakeLimiter(raise_error=RuntimeError("redis down"))
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_rate_limiter_failure_fail_open_allows_request(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/fail-open")

    assert response.status_code == 200


def test_authenticated_users_have_independent_buckets(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)

    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    with client as api_client:
        api_client.get("/api/v1/test/rate-limit/protected")

    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_b
    with client as api_client:
        api_client.get("/api/v1/test/rate-limit/protected")

    assert len(fake.hit_calls) == 2
    _, first_key, *_ = fake.hit_calls[0]
    _, second_key, *_ = fake.hit_calls[1]
    assert first_key != second_key


def test_health_endpoints_are_not_rate_limited(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    with client as api_client:
        response = api_client.get("/api/v1/health/live")
    assert response.status_code == 200


def test_unauthenticated_protected_endpoint_returns_401_before_rate_limiter(
    monkeypatch,
) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)

    with client as api_client:
        response = api_client.post("/api/v1/invites/accept", json={"token": "x"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_over_limit_does_not_execute_endpoint_body_or_database_io(monkeypatch) -> None:
    endpoint_body_called = False
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    app = client.app
    app.dependency_overrides[require_authenticated_principal] = _principal_user_a

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.connection = AsyncMock()
    session.begin = MagicMock()
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    session.get = AsyncMock()
    session.delete = AsyncMock()
    session.merge = AsyncMock()

    async def _db_override():
        yield session

    app.dependency_overrides[get_db_session] = _db_override

    router = APIRouter()
    policy = RateLimitPolicy(
        name="test_db_guard",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    @router.get(
        "/api/v1/test/rate-limit/db-guard",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe(
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, str]:
        nonlocal endpoint_body_called
        endpoint_body_called = True
        await db_session.execute("select 1")
        return {"ok": "true"}

    app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/db-guard")

    assert response.status_code == 429
    assert len(fake.hit_calls) == 1
    assert endpoint_body_called is False
    session.execute.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    session.refresh.assert_not_called()
    session.connection.assert_not_called()
    session.begin.assert_not_called()
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
    session.get.assert_not_called()
    session.delete.assert_not_called()
    session.merge.assert_not_called()


def test_unauthenticated_request_returns_401_without_limiter_or_database_io(
    monkeypatch,
) -> None:
    endpoint_body_called = False
    fake = FakeLimiter(allow=False, raise_error=RuntimeError("limiter must not run"))
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    app = client.app

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.connection = AsyncMock()
    session.begin = MagicMock()

    async def _db_override():
        yield session

    app.dependency_overrides[get_db_session] = _db_override

    router = APIRouter()
    policy = RateLimitPolicy(
        name="test_auth_before_rate_limit",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    @router.get(
        "/api/v1/test/rate-limit/auth-first",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe(
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, str]:
        nonlocal endpoint_body_called
        endpoint_body_called = True
        await db_session.execute("select 1")
        return {"ok": "true"}

    app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/auth-first")

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"
    assert endpoint_body_called is False
    assert len(fake.hit_calls) == 0
    session.execute.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    session.refresh.assert_not_called()
    session.connection.assert_not_called()
    session.begin.assert_not_called()


def test_rate_limiting_enablement_does_not_leak_between_apps(monkeypatch) -> None:
    first_client = _build_app(monkeypatch, enabled=True)
    with first_client:
        assert first_client.app.state.rate_limiter_runtime.enabled is False

    second_client = _build_app(monkeypatch, enabled=False)
    with second_client:
        assert second_client.app.state.rate_limiter_runtime.enabled is False


def test_invite_policies_are_distinct_and_declarative() -> None:
    assert INVITE_ACCEPT_POLICY.name == "invite_accept"
    assert INVITE_ACCEPT_POLICY.item.amount == 5
    assert INVITE_ACCEPT_POLICY.item.multiples == 5
    assert INVITE_ACCEPT_POLICY.item.get_expiry() == 300
    assert INVITE_ACCEPT_POLICY.fail_open is False

    assert INVITE_CREATE_POLICY.name == "invite_create"
    assert INVITE_CREATE_POLICY.item.amount == 20
    assert INVITE_CREATE_POLICY.item.get_expiry() == 3600
    assert INVITE_CREATE_POLICY.fail_open is False


def test_runtime_code_uses_limits_aio_namespace() -> None:
    from app.core.rate_limit import dependencies, lifecycle

    dependency_source = inspect.getsource(dependencies)
    lifecycle_source = inspect.getsource(lifecycle)

    assert "limits.aio" in dependency_source or "limits.aio" in lifecycle_source

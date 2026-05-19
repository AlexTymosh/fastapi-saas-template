from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.db.session import get_db_session
from app.core.rate_limit import AUTHENTICATED_DEFAULT_POLICY, rate_limit_dependency
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]


@dataclass
class _WindowStats:
    reset_time: float


class FakeLimiter:
    def __init__(self, *, allow: bool = True):
        self.allow = allow
        self.hit_calls: list[tuple[str, str, int, int]] = []
        self.window_calls: list[tuple[str, str, int, int]] = []

    async def hit(self, item, namespace: str, key: str) -> bool:
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
    )


def _build_app(
    monkeypatch,
    *,
    limiter: FakeLimiter,
    enabled: bool = True,
    client_host: str | None = None,
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        from app.core.rate_limit.registry import build_effective_policy_registry

        app.state.rate_limit_policy_registry = build_effective_policy_registry(settings)
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=enabled,
            storage=object() if enabled else None,
            limiter=limiter if enabled else None,
            strategy_name="moving-window" if enabled else None,
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true" if enabled else "false")
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "true")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET",
        "test-rate-limit-identifier-secret-32chars",
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()
    app = create_app()
    if client_host is not None:
        return TestClient(app, client=(client_host, 12345))
    return TestClient(app)


def test_invalid_token_request_can_be_pre_auth_rate_limited(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    client = _build_app(monkeypatch, limiter=fake)

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()

    async def _db_override():
        raise AssertionError(
            "DB session must not open for pre-auth over-limit requests"
        )
        yield  # pragma: no cover

    client.app.dependency_overrides[get_db_session] = _db_override

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.headers["retry-after"].isdigit()
    assert response.json()["error_code"] == "rate_limited"
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("test-rl:pre_auth:ip")
    session.execute.assert_not_called()


def test_missing_token_request_consumes_pre_auth_bucket_then_returns_401(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=True)
    client = _build_app(monkeypatch, limiter=fake)

    with client as api_client:
        response = api_client.get("/api/v1/users/me")

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("test-rl:pre_auth:ip")


def test_valid_authenticated_request_still_uses_user_post_auth_bucket(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=True)
    client = _build_app(monkeypatch, limiter=fake)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    router = APIRouter()

    @router.get(
        "/api/v1/test/pre-auth/post-auth",
        dependencies=[Depends(rate_limit_dependency(AUTHENTICATED_DEFAULT_POLICY))],
    )
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    client.app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/pre-auth/post-auth")

    assert response.status_code == 200
    assert len(fake.hit_calls) == 2
    assert fake.hit_calls[0][0].startswith("test-rl:pre_auth:ip")
    assert fake.hit_calls[1][0].startswith("test-rl:authenticated_default:user")


def test_health_endpoints_are_not_pre_auth_rate_limited(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    client = _build_app(monkeypatch, limiter=fake)

    with client as api_client:
        response = api_client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert fake.hit_calls == []


def test_direct_origin_request_is_rejected_in_edge_enforced_mode(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)
    client = _build_app(monkeypatch, limiter=fake, enabled=False)

    with client as api_client:
        response = api_client.get("/api/v1/users/me")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "forbidden"
    assert fake.hit_calls == []


def test_valid_edge_assertion_allows_edge_enforced_request(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", "e" * 32)
    client = _build_app(
        monkeypatch,
        limiter=fake,
        enabled=False,
        client_host="10.1.2.3",
    )

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me",
            headers={"X-Edge-Assertion": "e" * 32},
        )

    assert response.status_code == 401
    assert fake.hit_calls == []

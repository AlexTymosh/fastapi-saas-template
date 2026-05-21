from __future__ import annotations

import hmac
from dataclasses import dataclass
from hashlib import sha256
from unittest.mock import AsyncMock

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.config.settings import Settings
from app.core.db.session import get_db_session
from app.core.rate_limit import (
    AUTHENTICATED_DEFAULT_POLICY,
    TENANT_WRITE_POLICY,
    rate_limit_dependency,
)
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]

_EDGE_ASSERTION_SECRET = "e" * 32
_EDGE_ASSERTION_NOW = 1_900_000_000


@dataclass
class _WindowStats:
    reset_time: float


class FakeLimiter:
    def __init__(
        self,
        *,
        allow: bool = True,
        raise_error: Exception | None = None,
    ):
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
    )


def _edge_assertion_header(
    *,
    method: str = "GET",
    target: str = "/api/v1/users/me",
    timestamp: int = _EDGE_ASSERTION_NOW,
    secret: str = _EDGE_ASSERTION_SECRET,
) -> str:
    message = f"{timestamp}.{method.upper()}.{target}"
    signature = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).hexdigest()
    return f"t={timestamp},v1={signature}"


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


def _enable_edge_enforced_mode(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENFORCED_BY_EDGE", "true")
    monkeypatch.setenv("RATE_LIMITING__TRUSTED_PROXY_CIDRS", "10.0.0.0/8")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_HEADER_NAME", "X-Edge-Assertion")
    monkeypatch.setenv("RATE_LIMITING__EDGE_ASSERTION_SECRET", _EDGE_ASSERTION_SECRET)
    monkeypatch.setattr(
        "app.core.rate_limit.middleware.time.time",
        lambda: float(_EDGE_ASSERTION_NOW),
    )


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


def test_pre_auth_backend_failure_preserves_fail_open_read_policy(
    monkeypatch,
) -> None:
    fake = FakeLimiter(raise_error=RuntimeError("redis down"))
    client = _build_app(monkeypatch, limiter=fake)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    router = APIRouter()

    @router.get(
        "/api/v1/test/pre-auth/fail-open-read",
        dependencies=[Depends(rate_limit_dependency(AUTHENTICATED_DEFAULT_POLICY))],
    )
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    client.app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/pre-auth/fail-open-read")

    assert response.status_code == 200
    assert response.json() == {"ok": "true"}


def test_pre_auth_backend_failure_still_allows_fail_closed_policy_to_block(
    monkeypatch,
) -> None:
    fake = FakeLimiter(raise_error=RuntimeError("redis down"))
    client = _build_app(monkeypatch, limiter=fake)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    router = APIRouter()

    @router.post(
        "/api/v1/test/pre-auth/fail-closed-write",
        dependencies=[Depends(rate_limit_dependency(TENANT_WRITE_POLICY))],
    )
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    client.app.include_router(router)

    with client as api_client:
        response = api_client.post("/api/v1/test/pre-auth/fail-closed-write")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_health_endpoints_are_not_pre_auth_rate_limited(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    client = _build_app(monkeypatch, limiter=fake)

    with client as api_client:
        response = api_client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert fake.hit_calls == []


def test_health_endpoints_are_not_rejected_by_edge_assertion(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(monkeypatch, limiter=fake, enabled=False)

    with client as api_client:
        live_response = api_client.get("/api/v1/health/live")
        ready_response = api_client.get("/api/v1/health/ready")
        live_slash_response = api_client.get(
            "/api/v1/health/live/",
            follow_redirects=False,
        )
        ready_slash_response = api_client.get(
            "/api/v1/health/ready/",
            follow_redirects=False,
        )

    assert live_response.status_code == 200
    assert ready_response.status_code != 403
    assert live_slash_response.status_code != 403
    assert ready_slash_response.status_code != 403
    assert fake.hit_calls == []


def test_direct_origin_request_is_rejected_in_edge_enforced_mode(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(monkeypatch, limiter=fake, enabled=False)

    with client as api_client:
        response = api_client.get("/api/v1/users/me")

    assert response.status_code == 403
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "forbidden"
    assert fake.hit_calls == []


def test_valid_edge_assertion_allows_edge_enforced_request(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(
        monkeypatch,
        limiter=fake,
        enabled=False,
        client_host="10.1.2.3",
    )

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me",
            headers={"X-Edge-Assertion": _edge_assertion_header()},
        )

    assert response.status_code == 401
    assert fake.hit_calls == []


def test_static_edge_assertion_secret_is_rejected_in_edge_enforced_mode(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(
        monkeypatch,
        limiter=fake,
        enabled=False,
        client_host="10.1.2.3",
    )

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me",
            headers={"X-Edge-Assertion": _EDGE_ASSERTION_SECRET},
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert fake.hit_calls == []


def test_expired_edge_assertion_is_rejected_in_edge_enforced_mode(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(
        monkeypatch,
        limiter=fake,
        enabled=False,
        client_host="10.1.2.3",
    )

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me",
            headers={
                "X-Edge-Assertion": _edge_assertion_header(
                    timestamp=_EDGE_ASSERTION_NOW - 301,
                ),
            },
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert fake.hit_calls == []


def test_edge_assertion_is_bound_to_method_and_request_target(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(
        monkeypatch,
        limiter=fake,
        enabled=False,
        client_host="10.1.2.3",
    )

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me?probe=actual",
            headers={
                "X-Edge-Assertion": _edge_assertion_header(
                    method="POST",
                    target="/api/v1/users/me?probe=signed",
                ),
            },
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert fake.hit_calls == []


def test_edge_assertion_allows_exact_signed_query_target(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    _enable_edge_enforced_mode(monkeypatch)
    client = _build_app(
        monkeypatch,
        limiter=fake,
        enabled=False,
        client_host="10.1.2.3",
    )

    with client as api_client:
        response = api_client.get(
            "/api/v1/users/me?probe=signed",
            headers={
                "X-Edge-Assertion": _edge_assertion_header(
                    target="/api/v1/users/me?probe=signed",
                ),
            },
        )

    assert response.status_code == 401
    assert fake.hit_calls == []


def test_pre_auth_rate_limit_uses_injected_app_settings_not_global_cache(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=False)

    async def _fake_init_rate_limiter(app, settings) -> None:
        from app.core.rate_limit.registry import build_effective_policy_registry

        app.state.rate_limit_policy_registry = build_effective_policy_registry(settings)
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=True,
            storage=object(),
            limiter=fake,
            strategy_name="moving-window",
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)

    # Global cached settings intentionally disagree with the injected app settings.
    # The regression this test protects against: check_pre_auth_rate_limit()
    # used get_settings() and skipped the limiter when the global cache had
    # RATE_LIMITING__ENABLED=false.
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    reset_settings_cache()

    injected_settings = Settings(
        rate_limiting={
            "enabled": True,
            "pre_auth_enabled": True,
            "identifier_secret": "injected-rate-limit-identifier-secret",
            "redis_prefix": "injected-rl",
        }
    )

    app = create_app(settings=injected_settings)

    with TestClient(app) as api_client:
        response = api_client.get(
            "/api/v1/users/me",
            headers={"Authorization": "Bearer invalid-token"},
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("injected-rl:pre_auth:ip")

    reset_settings_cache()

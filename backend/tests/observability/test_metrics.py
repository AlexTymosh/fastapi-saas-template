from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from limits import RateLimitItemPerMinute

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.observability import metrics
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


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.calls.append((value, attributes))


class _FakeHistogram:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, str]]] = []

    def record(self, value: float, attributes: dict[str, str]) -> None:
        self.calls.append((value, attributes))


async def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
        platform_roles=[],
    )


def _build_app(
    monkeypatch, *, runtime: RateLimiterRuntime, fail_open: bool
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = runtime

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()

    app = create_app()
    probe_policy = RateLimitPolicy(
        name="test_probe",
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


def test_metrics_helpers_are_noop_without_sdk() -> None:
    metrics.record_rate_limit_decision(
        policy_name="invite_create",
        result="allowed",
        identifier_kind="user",
    )
    metrics.record_rate_limit_backend_error(
        policy_name="invite_create",
        identifier_kind="user",
        error_type="RuntimeError",
    )
    metrics.record_rate_limit_check_duration(
        policy_name="invite_create",
        result="allowed",
        identifier_kind="user",
        duration_seconds=0.01,
    )


def test_metrics_helpers_emit_only_low_cardinality_attributes(monkeypatch) -> None:
    requests_counter = _FakeCounter()
    backend_counter = _FakeCounter()
    duration_histogram = _FakeHistogram()
    monkeypatch.setattr(metrics, "rate_limit_requests_total", requests_counter)
    monkeypatch.setattr(metrics, "rate_limit_backend_errors_total", backend_counter)
    monkeypatch.setattr(metrics, "rate_limit_check_duration", duration_histogram)

    metrics.record_rate_limit_decision(
        policy_name="invite_create",
        result="allowed",
        identifier_kind="user",
    )
    metrics.record_rate_limit_backend_error(
        policy_name="invite_create",
        identifier_kind="user",
        error_type="RuntimeError",
    )
    metrics.record_rate_limit_check_duration(
        policy_name="invite_create",
        result="blocked",
        identifier_kind="user",
        duration_seconds=0.02,
    )

    forbidden_keys = {
        "user_id",
        "email",
        "organisation_id",
        "request_id",
        "trace_id",
        "path",
        "raw_path",
        "url",
        "ip",
        "client_ip",
        "token",
        "redis_key",
        "identifier",
        "identifier_value",
        "hashed_identifier",
    }

    for _, attributes in requests_counter.calls:
        assert set(attributes).issubset(metrics.ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS)
        assert set(attributes).isdisjoint(forbidden_keys)

    for _, attributes in backend_counter.calls:
        assert set(attributes).issubset(metrics.ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS)
        assert set(attributes).isdisjoint(forbidden_keys)

    for _, attributes in duration_histogram.calls:
        assert set(attributes).issubset(metrics.ALLOWED_RATE_LIMIT_ATTRIBUTE_KEYS)
        assert set(attributes).isdisjoint(forbidden_keys)


@pytest.mark.parametrize("result", ["allowed", "blocked", "backend_error", "fail_open"])
def test_record_rate_limit_check_duration_supports_all_results(
    monkeypatch, result: str
) -> None:
    duration_histogram = _FakeHistogram()
    monkeypatch.setattr(metrics, "rate_limit_check_duration", duration_histogram)

    metrics.record_rate_limit_check_duration(
        policy_name="invite_create",
        result=result,
        identifier_kind="user",
        duration_seconds=0.02,
    )

    assert len(duration_histogram.calls) == 1
    recorded_duration, attributes = duration_histogram.calls[0]
    assert isinstance(recorded_duration, float)
    assert recorded_duration >= 0
    assert attributes[metrics.RATE_LIMIT_ATTRIBUTE_POLICY] == "invite_create"
    assert attributes[metrics.RATE_LIMIT_ATTRIBUTE_RESULT] == result
    assert attributes[metrics.RATE_LIMIT_ATTRIBUTE_IDENTIFIER_KIND] == "user"


def test_get_route_template_returns_route_path() -> None:
    request = type(
        "RequestStub",
        (),
        {
            "scope": {
                "route": type(
                    "RouteStub",
                    (),
                    {"path": "/api/v1/organisations/{organisation_id}/invites"},
                )()
            }
        },
    )()

    assert (
        metrics.get_route_template(request)
        == "/api/v1/organisations/{organisation_id}/invites"
    )


def test_get_route_template_returns_unknown_without_route() -> None:
    request = type("RequestStub", (), {"scope": {}})()

    assert metrics.get_route_template(request) == "unknown"


def test_get_route_template_never_uses_raw_path() -> None:
    raw_path = f"/api/v1/organisations/{uuid4()}/invites"
    request = type("RequestStub", (), {"scope": {"path": raw_path}})()

    assert metrics.get_route_template(request) == "unknown"


def test_rate_limit_dependency_records_allowed(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=_FakeLimiter(allow=True),
        strategy_name="moving-window",
    )
    decisions: list[str] = []

    with patch(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        side_effect=lambda **kwargs: decisions.append(kwargs["result"]),
    ):
        client = _build_app(monkeypatch, runtime=runtime, fail_open=False)
        with client as api_client:
            response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 200
    assert decisions == ["allowed"]


def test_rate_limit_dependency_records_blocked(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=_FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    decisions: list[str] = []

    with patch(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        side_effect=lambda **kwargs: decisions.append(kwargs["result"]),
    ):
        client = _build_app(monkeypatch, runtime=runtime, fail_open=False)
        with client as api_client:
            response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 429
    assert decisions == ["blocked"]


def test_rate_limit_dependency_records_backend_error_fail_closed(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=_FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    decisions: list[str] = []
    backend_errors: list[str] = []

    with (
        patch(
            "app.core.rate_limit.dependencies.record_rate_limit_decision",
            side_effect=lambda **kwargs: decisions.append(kwargs["result"]),
        ),
        patch(
            "app.core.rate_limit.dependencies.record_rate_limit_backend_error",
            side_effect=lambda **kwargs: backend_errors.append(kwargs["error_type"]),
        ),
    ):
        client = _build_app(monkeypatch, runtime=runtime, fail_open=False)
        with client as api_client:
            response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert decisions == ["backend_error"]
    assert backend_errors == ["RuntimeError"]


def test_rate_limit_dependency_records_fail_open(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=_FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    decisions: list[str] = []

    with patch(
        "app.core.rate_limit.dependencies.record_rate_limit_decision",
        side_effect=lambda **kwargs: decisions.append(kwargs["result"]),
    ):
        client = _build_app(monkeypatch, runtime=runtime, fail_open=True)
        with client as api_client:
            response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 200
    assert decisions == ["fail_open"]

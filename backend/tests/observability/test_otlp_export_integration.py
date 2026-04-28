from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from inspect import isawaitable

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient
from limits import RateLimitItemPerMinute
from opentelemetry import metrics
from testcontainers.core.container import DockerContainer

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import RateLimitPolicy
from app.main import create_app
from tests.helpers.settings import reset_settings_cache


def _decode_logs_payload(log_payload: object) -> str:
    if isinstance(log_payload, tuple):
        return "\n".join(_decode_logs_payload(part) for part in log_payload)
    if isinstance(log_payload, bytes):
        return log_payload.decode("utf-8", errors="replace")
    if isinstance(log_payload, str):
        return log_payload
    if isinstance(log_payload, Iterable):
        return "\n".join(_decode_logs_payload(part) for part in log_payload)
    return str(log_payload)


def _wait_for_collector_logs(
    *,
    container: DockerContainer,
    expected_substrings: list[str],
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.3,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_logs = ""

    while time.monotonic() < deadline:
        raw_logs = container.get_logs()
        logs = _decode_logs_payload(raw_logs)
        if logs:
            last_logs = logs

        if all(substring in logs for substring in expected_substrings):
            return logs

        time.sleep(poll_interval_seconds)

    pytest.fail(
        "Timed out waiting for OTLP metrics in Collector logs. "
        f"Expected substrings: {expected_substrings}. "
        f"Last logs:\n{last_logs}"
    )


async def _force_flush_metrics() -> None:
    provider = metrics.get_meter_provider()
    force_flush = getattr(provider, "force_flush", None)
    if force_flush is None:
        return
    result = force_flush()
    if isawaitable(result):
        await result


class FailingLimiter:
    async def hit(self, item, namespace: str, key: str) -> bool:
        raise RuntimeError("redis down")


@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.anyio
async def test_otlp_collector_receives_http_metrics_export(
    monkeypatch,
    otel_collector_container: DockerContainer,
    otlp_metrics_endpoint: str,
    redis_integration_url: str,
) -> None:
    test_suffix = uuid.uuid4().hex
    redis_prefix = f"it-otlp-rl-{test_suffix}"
    policy_name = f"otlp_rate_limit_probe_{test_suffix}"

    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.setenv("OBSERVABILITY__OTLP_ENDPOINT", otlp_metrics_endpoint)
    monkeypatch.setenv("OBSERVABILITY__SERVICE_NAME", "fastapi-saas-template-test")
    monkeypatch.setenv("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "100")
    monkeypatch.setenv("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "1000")
    monkeypatch.setenv("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", redis_prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")

    reset_settings_cache()
    app = create_app()

    async def _principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id=f"otlp-rate-limit-user-{test_suffix}",
            email="integration-user@example.com",
            email_verified=True,
            platform_roles=[],
        )

    app.dependency_overrides[get_authenticated_principal] = _principal

    router = APIRouter()
    policy = RateLimitPolicy(
        name=policy_name,
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    @router.get(
        "/api/v1/integration/rate-limit-otlp",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health_response = await client.get("/api/v1/health/live")
            first_response = await client.get("/api/v1/integration/rate-limit-otlp")
            second_response = await client.get("/api/v1/integration/rate-limit-otlp")

    assert health_response.status_code == 200
    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.json()["error_code"] == "rate_limited"
    assert second_response.headers["retry-after"].isdigit()

    logs = _wait_for_collector_logs(
        container=otel_collector_container,
        expected_substrings=[
            "http.server.request.duration",
            "http.server.requests.total",
            "fastapi-saas-template-test",
            "rate_limit.requests.total",
            "rate_limit.check.duration",
            "rate_limit.policy",
            "rate_limit.result",
            policy_name,
            "allowed",
            "blocked",
        ],
    )

    assert "/api/v1/health/live" in logs
    assert "/api/v1/integration/rate-limit-otlp" in logs
    assert "200" in logs
    assert "429" in logs


@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.anyio
async def test_otlp_collector_receives_rate_limit_backend_errors_export(
    monkeypatch,
    otel_collector_container: DockerContainer,
    otlp_metrics_endpoint: str,
    redis_integration_url: str,
) -> None:
    test_suffix = uuid.uuid4().hex
    redis_prefix = f"it-otlp-rl-backend-{test_suffix}"
    fail_closed_policy_name = f"otlp_rate_limit_backend_error_{test_suffix}"
    fail_open_policy_name = f"otlp_rate_limit_fail_open_{test_suffix}"
    runtime_unavailable_policy_name = (
        f"otlp_rate_limit_runtime_unavailable_{test_suffix}"
    )

    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.setenv("OBSERVABILITY__OTLP_ENDPOINT", otlp_metrics_endpoint)
    monkeypatch.setenv("OBSERVABILITY__SERVICE_NAME", "fastapi-saas-template-test")
    monkeypatch.setenv("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "100")
    monkeypatch.setenv("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "1000")
    monkeypatch.setenv("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", redis_prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")

    reset_settings_cache()
    app = create_app()

    async def _principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id=f"otlp-rate-limit-user-{test_suffix}",
            email="integration-user@example.com",
            email_verified=True,
            platform_roles=[],
        )

    app.dependency_overrides[get_authenticated_principal] = _principal

    router = APIRouter()
    fail_closed_policy = RateLimitPolicy(
        name=fail_closed_policy_name,
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )
    fail_open_policy = RateLimitPolicy(
        name=fail_open_policy_name,
        item=RateLimitItemPerMinute(1),
        fail_open=True,
    )
    runtime_unavailable_policy = RateLimitPolicy(
        name=runtime_unavailable_policy_name,
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    @router.get(
        "/api/v1/integration/rate-limit-backend-error",
        dependencies=[Depends(rate_limit_dependency(fail_closed_policy))],
    )
    async def _fail_closed_probe() -> dict[str, str]:
        return {"ok": "true"}

    @router.get(
        "/api/v1/integration/rate-limit-fail-open",
        dependencies=[Depends(rate_limit_dependency(fail_open_policy))],
    )
    async def _fail_open_probe() -> dict[str, str]:
        return {"ok": "true"}

    @router.get(
        "/api/v1/integration/rate-limit-runtime-unavailable",
        dependencies=[Depends(rate_limit_dependency(runtime_unavailable_policy))],
    )
    async def _runtime_unavailable_probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)

    async with app.router.lifespan_context(app):
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=True,
            storage=object(),
            limiter=FailingLimiter(),
            strategy_name="moving-window",
        )

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            fail_closed_response = await client.get(
                "/api/v1/integration/rate-limit-backend-error"
            )
            fail_open_response = await client.get(
                "/api/v1/integration/rate-limit-fail-open"
            )
            app.state.rate_limiter_runtime = RateLimiterRuntime(
                enabled=True,
                storage=object(),
                limiter=None,
                strategy_name="moving-window",
            )
            runtime_unavailable_response = await client.get(
                "/api/v1/integration/rate-limit-runtime-unavailable"
            )

        await _force_flush_metrics()

    assert fail_closed_response.status_code == 503
    assert fail_closed_response.json()["error_code"] == "rate_limiter_unavailable"
    assert fail_open_response.status_code == 200
    assert runtime_unavailable_response.status_code == 503
    assert (
        runtime_unavailable_response.json()["error_code"] == "rate_limiter_unavailable"
    )

    _wait_for_collector_logs(
        container=otel_collector_container,
        expected_substrings=[
            "rate_limit.backend_errors.total",
            "rate_limit.requests.total",
            "rate_limit.check.duration",
            "rate_limit.policy",
            "rate_limit.result",
            "error.type",
            "backend_error",
            "fail_open",
            "runtime_unavailable",
            "RuntimeError",
            "RuntimeUnavailable",
            fail_closed_policy_name,
            fail_open_policy_name,
            runtime_unavailable_policy_name,
        ],
    )

from __future__ import annotations

import time
from collections.abc import Iterable

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.core.container import DockerContainer

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


@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.anyio
async def test_otlp_collector_receives_http_metrics_export(
    monkeypatch,
    otel_collector_container: DockerContainer,
    otlp_metrics_endpoint: str,
) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.setenv("OBSERVABILITY__OTLP_ENDPOINT", otlp_metrics_endpoint)
    monkeypatch.setenv("OBSERVABILITY__SERVICE_NAME", "fastapi-saas-template-test")
    monkeypatch.setenv("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "100")
    monkeypatch.setenv("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "1000")
    monkeypatch.setenv("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "1.0")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")

    reset_settings_cache()
    app = create_app()

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/health/live")

    assert response.status_code == 200

    logs = _wait_for_collector_logs(
        container=otel_collector_container,
        expected_substrings=[
            "http.server.request.duration",
            "http.server.requests.total",
            "fastapi-saas-template-test",
        ],
    )

    assert "/api/v1/health/live" in logs
    assert "200" in logs

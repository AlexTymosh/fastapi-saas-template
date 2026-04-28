from __future__ import annotations

import time

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.core.container import DockerContainer

from app.main import create_app
from tests.helpers.settings import reset_settings_cache


def _wait_for_collector_logs(
    container: DockerContainer,
    *,
    expected_substrings: tuple[str, ...],
    timeout_seconds: float = 30.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_logs = ""

    while True:
        raw_logs = container.get_logs()
        if isinstance(raw_logs, tuple):
            raw_logs = b"\n".join(
                chunk if isinstance(chunk, bytes) else str(chunk).encode("utf-8")
                for chunk in raw_logs
                if chunk
            )

        if isinstance(raw_logs, bytes):
            decoded_logs = raw_logs.decode("utf-8", errors="replace")
        else:
            decoded_logs = str(raw_logs)

        if decoded_logs:
            last_logs = decoded_logs

        if all(substring in decoded_logs for substring in expected_substrings):
            return decoded_logs

        if time.monotonic() >= deadline:
            pytest.fail(
                "Timed out waiting for OTLP metrics in collector logs. "
                f"Expected substrings: {expected_substrings}. "
                f"Last collector logs:\n{last_logs}"
            )

        time.sleep(0.3)


@pytest.mark.integration
@pytest.mark.anyio
async def test_otlp_collector_receives_http_metrics_export(
    monkeypatch,
    otlp_metrics_endpoint: str,
    otel_collector_container: DockerContainer,
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
        otel_collector_container,
        expected_substrings=(
            "http.server.request.duration",
            "http.server.requests.total",
            "fastapi-saas-template-test",
        ),
    )
    assert "/api/v1/health/live" in logs
    assert "200" in logs

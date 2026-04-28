from __future__ import annotations

import time
from collections.abc import Iterable

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.core.container import DockerContainer

from app.main import create_app
from tests.helpers.settings import reset_settings_cache


def _decode_collector_logs(raw_logs: bytes | str | tuple[object, ...]) -> str:
    if isinstance(raw_logs, tuple):
        return "\n".join(_decode_collector_logs(part) for part in raw_logs)
    if isinstance(raw_logs, bytes):
        return raw_logs.decode("utf-8", errors="replace")
    if isinstance(raw_logs, str):
        return raw_logs
    return str(raw_logs)


def _wait_for_collector_logs(
    *,
    container: DockerContainer,
    expected_substrings: Iterable[str],
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.3,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    expected = list(expected_substrings)
    latest_logs = ""

    while time.monotonic() < deadline:
        latest_logs = _decode_collector_logs(container.get_logs())
        if all(snippet in latest_logs for snippet in expected):
            return
        time.sleep(poll_interval_seconds)

    pytest.fail(
        "Timed out waiting for OTLP collector logs to contain expected substrings "
        f"{expected}. Latest logs:\n{latest_logs}"
    )


@pytest.mark.integration
@pytest.mark.e2e
@pytest.mark.anyio
async def test_otlp_collector_receives_http_metrics_export(
    monkeypatch: pytest.MonkeyPatch,
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

    _wait_for_collector_logs(
        container=otel_collector_container,
        expected_substrings=(
            "http.server.request.duration",
            "http.server.requests.total",
            "fastapi-saas-template-test",
        ),
    )

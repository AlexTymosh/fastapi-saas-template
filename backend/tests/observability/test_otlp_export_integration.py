from __future__ import annotations

import socket
import time
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from testcontainers.core.container import DockerContainer

from app.main import create_app
from tests.helpers.settings import reset_settings_cache

_COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.122.1"
_COLLECTOR_OTLP_HTTP_PORT = 4318


@pytest.fixture
def otel_collector_container(tmp_path: Path) -> DockerContainer:
    collector_config = tmp_path / "otel-collector.yaml"
    collector_config.write_text(
        """
receivers:
  otlp:
    protocols:
      http:
        endpoint: 0.0.0.0:4318

exporters:
  debug:
    verbosity: detailed

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [debug]
""".strip()
        + "\n",
        encoding="utf-8",
    )

    container = (
        DockerContainer(_COLLECTOR_IMAGE)
        .with_exposed_ports(_COLLECTOR_OTLP_HTTP_PORT)
        .with_bind_mount(
            str(collector_config),
            "/etc/otel-collector.yaml",
            mode="ro",
        )
        .with_command("--config=/etc/otel-collector.yaml")
    )

    with container:
        host = container.get_container_host_ip()
        mapped_port = int(container.get_exposed_port(_COLLECTOR_OTLP_HTTP_PORT))
        _wait_for_tcp_port(host=host, port=mapped_port, timeout_seconds=45.0)
        yield container


@pytest.fixture
def otlp_metrics_endpoint(otel_collector_container: DockerContainer) -> str:
    host = otel_collector_container.get_container_host_ip()
    mapped_port = int(
        otel_collector_container.get_exposed_port(_COLLECTOR_OTLP_HTTP_PORT)
    )
    return f"http://{host}:{mapped_port}/v1/metrics"


def _wait_for_tcp_port(*, host: str, port: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds

    while True:
        try:
            with socket.create_connection((host, port), timeout=1.0):
                return
        except OSError:
            if time.monotonic() >= deadline:
                pytest.fail(
                    "OpenTelemetry Collector did not become ready on "
                    f"{host}:{port} within {timeout_seconds:.1f}s"
                )
            time.sleep(0.2)


def _read_container_logs(container: DockerContainer) -> str:
    logs: Any = container.get_logs()

    if isinstance(logs, tuple):
        logs = b"\n".join(part for part in logs if part)

    if isinstance(logs, bytes):
        return logs.decode("utf-8", errors="replace")

    return str(logs)


def _wait_for_collector_logs(
    container: DockerContainer,
    *,
    expected_substrings: tuple[str, ...],
    timeout_seconds: float = 30.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_logs = ""

    while True:
        last_logs = _read_container_logs(container)
        if all(expected in last_logs for expected in expected_substrings):
            return last_logs

        if time.monotonic() >= deadline:
            pytest.fail(
                "Timed out waiting for expected Collector metric logs: "
                f"{expected_substrings}. Last logs:\n{last_logs}"
            )

        time.sleep(0.3)


@pytest.mark.integration
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
        otel_collector_container,
        expected_substrings=(
            "http.server.request.duration",
            "http.server.requests.total",
            "fastapi-saas-template-test",
        ),
        timeout_seconds=30.0,
    )
    assert "http.response.status_code" in logs

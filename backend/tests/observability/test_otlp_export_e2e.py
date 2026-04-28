from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from docker.errors import DockerException
from testcontainers.core.container import DockerContainer

COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.122.1"


@pytest.mark.integration
def test_otlp_metrics_are_exported_via_collector_debug_exporter(tmp_path: Path) -> None:
    backend_root = _backend_root()
    collector_config = _collector_config(tmp_path)

    try:
        with _run_collector(collector_config) as collector:
            collector_host = collector.get_container_host_ip()
            collector_port = int(collector.get_exposed_port(4318))
            _wait_for_tcp_port(host=collector_host, port=collector_port)

            otlp_endpoint = f"http://{collector_host}:{collector_port}/v1/metrics"
            completed = _run_app_subprocess(
                backend_root=backend_root,
                otlp_endpoint=otlp_endpoint,
            )

            expected_metrics = [
                "http.server.request.duration",
                "http.server.requests.total",
                "fastapi-saas-template-e2e",
            ]

            if completed.returncode != 0:
                collector_logs = collector.get_logs().decode("utf-8", errors="replace")
                pytest.fail(
                    "Application subprocess failed.\n"
                    f"Return code: {completed.returncode}\n"
                    f"--- stdout ---\n{completed.stdout}\n"
                    f"--- stderr ---\n{completed.stderr}\n"
                    f"--- collector logs ---\n{collector_logs}"
                )

            collector_logs = _wait_for_collector_logs(
                collector=collector,
                expected=expected_metrics,
                timeout_seconds=12.0,
            )

            assert "http.server.request.duration" in collector_logs
            assert "http.server.requests.total" in collector_logs
            assert "fastapi-saas-template-e2e" in collector_logs
            assert "/api/v1/health/live" in collector_logs
            assert "int_value: 200" in collector_logs
    except (DockerException, OSError) as error:
        pytest.skip(f"Docker is unavailable for OTLP integration test: {error}")


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _collector_config(tmp_path: Path) -> Path:
    config_path = tmp_path / "otel-collector-test.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            receivers:
              otlp:
                protocols:
                  http:
                    endpoint: 0.0.0.0:4318

            exporters:
              debug:
                verbosity: detailed

            processors:
              batch:

            service:
              pipelines:
                metrics:
                  receivers: [otlp]
                  processors: [batch]
                  exporters: [debug]
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return config_path


def _run_app_subprocess(
    *, backend_root: Path, otlp_endpoint: str
) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient

        from app.main import create_app


        with TestClient(create_app()) as client:
            for _ in range(6):
                response = client.get("/api/v1/health/live")
                assert response.status_code == 200
        """
    )
    env = os.environ.copy()
    env.update(
        {
            "OBSERVABILITY__METRICS_ENABLED": "true",
            "OBSERVABILITY__EXPORTER": "otlp",
            "OBSERVABILITY__OTLP_ENDPOINT": otlp_endpoint,
            "OBSERVABILITY__SERVICE_NAME": "fastapi-saas-template-e2e",
            "OBSERVABILITY__EXPORT_INTERVAL_MILLIS": "200",
            "OBSERVABILITY__EXPORT_TIMEOUT_MILLIS": "1000",
            "OBSERVABILITY__OTLP_TIMEOUT_SECONDS": "2.0",
            "RATE_LIMITING__ENABLED": "false",
            "VAULT__ENABLED": "false",
            "APP__ENVIRONMENT": "test",
            "LOGGING__AS_JSON": "true",
        }
    )

    pythonpath_items = [str(backend_root)]
    existing_pythonpath = env.get("PYTHONPATH")
    if existing_pythonpath:
        pythonpath_items.append(existing_pythonpath)
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_items)

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_collector(config_path: Path) -> DockerContainer:
    return (
        DockerContainer(COLLECTOR_IMAGE)
        .with_exposed_ports(4318)
        .with_volume_mapping(str(config_path), "/etc/otelcol/config.yaml")
        .with_command("--config /etc/otelcol/config.yaml")
    )


def _wait_for_tcp_port(*, host: str, port: int, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            if probe.connect_ex((host, port)) == 0:
                return
        time.sleep(0.2)

    raise AssertionError(f"Collector TCP endpoint {host}:{port} did not become ready")


def _wait_for_collector_logs(
    *,
    collector: DockerContainer,
    expected: list[str],
    timeout_seconds: float = 10.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    logs = ""

    while time.monotonic() < deadline:
        logs = collector.get_logs().decode("utf-8", errors="replace")
        if all(token in logs for token in expected):
            return logs
        time.sleep(0.25)

    missing = [token for token in expected if token not in logs]
    raise AssertionError(
        "Collector logs did not contain expected metrics markers within timeout.\n"
        f"Missing markers: {missing}\n"
        f"--- collector logs ---\n{logs}"
    )

from __future__ import annotations

import os
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer

COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.122.1"


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _collector_config(tmp_path: Path) -> Path:
    config = textwrap.dedent(
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
    config_path = tmp_path / "otel-collector-test.yaml"
    config_path.write_text(config, encoding="utf-8")
    return config_path


def _wait_for_port(host: str, port: int, timeout_seconds: float = 15.0) -> None:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.5)
            if sock.connect_ex((host, port)) == 0:
                return
        time.sleep(0.2)

    raise AssertionError(
        f"Collector OTLP HTTP port {host}:{port} did not become ready within "
        f"{timeout_seconds} seconds"
    )


def _run_app_subprocess(
    *, backend_root: Path, otlp_endpoint: str
) -> subprocess.CompletedProcess[str]:
    script = textwrap.dedent(
        """
        from fastapi.testclient import TestClient

        from app.main import create_app


        with TestClient(create_app()) as client:
            for _ in range(3):
                response = client.get("/api/v1/health/live")
                assert response.status_code == 200
        """
    )

    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(backend_root)
        if not existing_pythonpath
        else f"{backend_root}{os.pathsep}{existing_pythonpath}"
    )

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

    return subprocess.run(
        [sys.executable, "-c", script],
        cwd=backend_root,
        env=env,
        timeout=30,
        capture_output=True,
        text=True,
        check=False,
    )


def _wait_for_collector_logs(
    container: DockerContainer,
    expected: list[str],
    timeout_seconds: float = 12.0,
) -> str:
    deadline = time.monotonic() + timeout_seconds
    last_logs = ""

    while time.monotonic() < deadline:
        raw_logs = container.get_logs()
        if isinstance(raw_logs, tuple):
            combined = b"".join(part for part in raw_logs if part)
        elif isinstance(raw_logs, bytes):
            combined = raw_logs
        elif isinstance(raw_logs, str):
            combined = raw_logs.encode("utf-8", errors="replace")
        else:
            combined = str(raw_logs).encode("utf-8", errors="replace")

        last_logs = combined.decode("utf-8", errors="replace")

        if all(marker in last_logs for marker in expected):
            return last_logs

        time.sleep(0.3)

    missing = [marker for marker in expected if marker not in last_logs]
    raise AssertionError(
        "Timed out waiting for expected collector log markers. "
        f"Missing markers: {missing}.\nCollector logs:\n{last_logs}"
    )


def _decode_container_logs(raw_logs: object) -> str:
    if isinstance(raw_logs, tuple):
        return b"".join(part for part in raw_logs if part).decode(
            "utf-8", errors="replace"
        )
    if isinstance(raw_logs, bytes):
        return raw_logs.decode("utf-8", errors="replace")
    return str(raw_logs)


@pytest.mark.integration
def test_otlp_http_export_sends_metrics_to_collector_debug_exporter(tmp_path: Path):
    backend_root = _backend_root()
    collector_config = _collector_config(tmp_path)

    with (
        DockerContainer(COLLECTOR_IMAGE)
        .with_exposed_ports(4318)
        .with_volume_mapping(
            str(collector_config), "/etc/otel-collector-test.yaml", mode="ro"
        )
        .with_command("--config=/etc/otel-collector-test.yaml")
    ) as collector:
        collector_host = collector.get_container_host_ip()
        collector_port = int(collector.get_exposed_port(4318))

        _wait_for_port(collector_host, collector_port)

        otlp_endpoint = f"http://{collector_host}:{collector_port}/v1/metrics"
        result = _run_app_subprocess(
            backend_root=backend_root,
            otlp_endpoint=otlp_endpoint,
        )

        collector_logs = _decode_container_logs(collector.get_logs())

        assert result.returncode == 0, (
            "App subprocess failed.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}\n"
            f"Collector logs:\n{collector_logs}"
        )

        collector_logs = _wait_for_collector_logs(
            collector,
            expected=[
                "http.server.request.duration",
                "http.server.requests.total",
                "fastapi-saas-template-e2e",
            ],
        )

        assert "http.server.request.duration" in collector_logs
        assert "http.server.requests.total" in collector_logs
        assert "fastapi-saas-template-e2e" in collector_logs
        assert "/api/v1/health/live" in collector_logs
        assert "http.response.status_code: Int(200)" in collector_logs

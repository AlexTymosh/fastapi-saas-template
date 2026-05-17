from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from testcontainers.core.container import DockerContainer

from tests.fixtures.containers import wait_for_container_log, wait_for_tcp_readiness


def _build_otel_collector_config(config_path: Path) -> None:
    config_path.write_text(
        "\n".join(
            [
                "receivers:",
                "  otlp:",
                "    protocols:",
                "      http:",
                "        endpoint: 0.0.0.0:4318",
                "",
                "exporters:",
                "  debug:",
                "    verbosity: detailed",
                "",
                "service:",
                "  pipelines:",
                "    metrics:",
                "      receivers: [otlp]",
                "      exporters: [debug]",
                "",
            ]
        ),
        encoding="utf-8",
    )


@pytest.fixture(scope="session")
def otel_collector_container(tmp_path_factory) -> Iterator[DockerContainer]:
    config_dir = tmp_path_factory.mktemp("otel-collector")
    config_path = config_dir / "otel-collector.yaml"
    _build_otel_collector_config(config_path)

    container = (
        DockerContainer("otel/opentelemetry-collector-contrib:0.122.1")
        .with_exposed_ports(4318)
        .with_volume_mapping(
            str(config_path.resolve()),
            "/etc/otel-collector.yaml",
            mode="ro",
        )
        .with_command("--config=/etc/otel-collector.yaml")
    )

    with container:
        host = container.get_container_host_ip()
        port = int(container.get_exposed_port(4318))
        wait_for_tcp_readiness(host=host, port=port, timeout_seconds=30.0)
        wait_for_container_log(
            container,
            expected_substring="Everything is ready",
            timeout_seconds=30.0,
        )
        yield container


@pytest.fixture(scope="session")
def otlp_metrics_endpoint(otel_collector_container: DockerContainer) -> str:
    host = otel_collector_container.get_container_host_ip()
    port = otel_collector_container.get_exposed_port(4318)
    return f"http://{host}:{port}/v1/metrics"

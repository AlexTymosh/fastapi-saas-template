from __future__ import annotations

import time
from collections.abc import Iterable
from socket import create_connection

import pytest
from testcontainers.core.container import DockerContainer


def wait_for_tcp_readiness(*, host: str, port: int, timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            with create_connection((host, port), timeout=1.0):
                return
        except OSError:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Timed out waiting for TCP readiness at {host}:{port}"
                ) from None
            time.sleep(0.2)


def decode_container_logs(log_payload: object) -> str:
    if isinstance(log_payload, tuple):
        return "\n".join(decode_container_logs(part) for part in log_payload)
    if isinstance(log_payload, bytes):
        return log_payload.decode("utf-8", errors="replace")
    if isinstance(log_payload, str):
        return log_payload
    if isinstance(log_payload, Iterable):
        return "\n".join(decode_container_logs(part) for part in log_payload)
    return str(log_payload)


def wait_for_container_log(
    container: DockerContainer,
    *,
    expected_substring: str,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.2,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    latest_logs = ""

    while time.monotonic() < deadline:
        logs = decode_container_logs(container.get_logs())
        if logs:
            latest_logs = logs
        if expected_substring in logs:
            return
        time.sleep(poll_interval_seconds)

    pytest.fail(
        "Timed out waiting for container log readiness. "
        f"Expected substring: {expected_substring!r}. "
        f"Latest container logs:\n{latest_logs}"
    )

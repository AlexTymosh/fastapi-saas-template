from __future__ import annotations

import time
from collections.abc import Iterator

import pytest
from redis import Redis
from redis.exceptions import BusyLoadingError
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError
from testcontainers.core.container import DockerContainer


@pytest.fixture(scope="session")
def redis_integration_url() -> Iterator[str]:
    """
    Start an ephemeral Redis instance for integration tests.
    """
    with DockerContainer("redis:7-alpine").with_exposed_ports(6379) as redis_container:
        host = redis_container.get_container_host_ip()
        port = redis_container.get_exposed_port(6379)
        redis_url = f"redis://{host}:{port}/0"

        client = Redis.from_url(redis_url)
        deadline = time.monotonic() + 30

        try:
            while True:
                try:
                    client.ping()
                    break
                except (RedisConnectionError, RedisTimeoutError, BusyLoadingError):
                    if time.monotonic() >= deadline:
                        raise
                    time.sleep(0.2)

            yield redis_url
        finally:
            client.close()

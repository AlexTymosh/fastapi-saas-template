from __future__ import annotations

from tests.fixtures.otel import otel_collector_container as otel_collector_container
from tests.fixtures.otel import otlp_metrics_endpoint as otlp_metrics_endpoint
from tests.fixtures.redis import redis_integration_url as redis_integration_url

__all__ = [
    "otel_collector_container",
    "otlp_metrics_endpoint",
    "redis_integration_url",
]

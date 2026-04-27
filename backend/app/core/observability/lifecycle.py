from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from opentelemetry import metrics as otel_metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, Resource

from app.core.config.settings import Settings
from app.core.logging import get_logger


@dataclass
class ObservabilityRuntime:
    meter_provider: MeterProvider | None
    initialized: bool


_runtime = ObservabilityRuntime(meter_provider=None, initialized=False)


async def init_observability(settings: Settings) -> None:
    observability = settings.observability

    if _runtime.initialized:
        return

    if not observability.metrics_enabled:
        return

    if observability.exporter == "none":
        return

    if observability.exporter != "otlp":
        raise RuntimeError("Unsupported observability exporter configuration")

    if not observability.otlp_endpoint:
        raise RuntimeError(
            "OBSERVABILITY__OTLP_ENDPOINT is required when "
            "OBSERVABILITY__METRICS_ENABLED=true and OBSERVABILITY__EXPORTER=otlp"
        )

    service_name = observability.service_name or settings.app.name
    resource = Resource.create({SERVICE_NAME: service_name})

    exporter = OTLPMetricExporter(
        endpoint=observability.otlp_endpoint,
        timeout=observability.otlp_timeout_seconds,
    )

    reader = PeriodicExportingMetricReader(
        exporter,
        export_interval_millis=observability.export_interval_millis,
        export_timeout_millis=observability.export_timeout_millis,
    )

    provider = MeterProvider(metric_readers=[reader], resource=resource)
    otel_metrics.set_meter_provider(provider)

    _runtime.meter_provider = provider
    _runtime.initialized = True


async def shutdown_observability() -> None:
    log = get_logger(__name__)
    provider = _runtime.meter_provider

    _runtime.meter_provider = None
    _runtime.initialized = False

    if provider is None:
        return

    for operation_name in ("force_flush", "shutdown"):
        operation = getattr(provider, operation_name, None)
        if not callable(operation):
            continue

        try:
            result: Any = operation()
            if hasattr(result, "__await__"):
                await result
        except Exception as exc:
            log.warning(
                "observability_shutdown_operation_failed",
                operation=operation_name,
                error_type=exc.__class__.__name__,
                category="observability",
            )

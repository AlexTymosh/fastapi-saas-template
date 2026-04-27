from __future__ import annotations

from typing import Any

from opentelemetry import metrics

from app.core.config.settings import Settings
from app.core.logging import get_logger

log = get_logger(__name__)
_initialized_provider: Any | None = None


def _build_service_name(settings: Settings) -> str:
    return settings.observability.service_name or settings.app.name


def _load_otlp_metric_exporter() -> type[Any]:
    from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
        OTLPMetricExporter,
    )

    return OTLPMetricExporter


def _load_meter_provider() -> type[Any]:
    from opentelemetry.sdk.metrics import MeterProvider

    return MeterProvider


def _load_periodic_exporting_metric_reader() -> type[Any]:
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    return PeriodicExportingMetricReader


def _build_resource(service_name: str) -> Any:
    from opentelemetry.sdk.resources import Resource

    return Resource.create({"service.name": service_name})


async def init_observability(settings: Settings) -> None:
    global _initialized_provider

    if _initialized_provider is not None:
        return

    if not settings.observability.metrics_enabled:
        return

    if settings.observability.exporter == "none":
        return

    if settings.observability.exporter != "otlp":
        return

    endpoint = settings.observability.otlp_endpoint
    if not endpoint:
        raise RuntimeError(
            "OBSERVABILITY__OTLP_ENDPOINT is required when "
            "OBSERVABILITY__METRICS_ENABLED=true and OBSERVABILITY__EXPORTER=otlp"
        )

    otlp_metric_exporter = _load_otlp_metric_exporter()
    periodic_reader_cls = _load_periodic_exporting_metric_reader()
    meter_provider_cls = _load_meter_provider()

    exporter = otlp_metric_exporter(
        endpoint=endpoint,
        timeout=settings.observability.otlp_timeout_seconds,
    )
    reader = periodic_reader_cls(
        exporter,
        export_interval_millis=settings.observability.export_interval_millis,
        export_timeout_millis=settings.observability.export_timeout_millis,
    )
    resource = _build_resource(_build_service_name(settings))
    provider = meter_provider_cls(metric_readers=[reader], resource=resource)

    metrics.set_meter_provider(provider)
    _initialized_provider = provider
    log.info(
        "observability_metrics_initialized",
        exporter="otlp_http",
        category="observability",
    )


async def shutdown_observability() -> None:
    global _initialized_provider

    provider = _initialized_provider
    _initialized_provider = None

    if provider is None:
        return

    try:
        provider.force_flush()
    except Exception as exc:
        log.warning(
            "observability_metrics_force_flush_failed",
            reason=exc.__class__.__name__,
            category="observability",
        )

    try:
        provider.shutdown()
    except Exception as exc:
        log.warning(
            "observability_metrics_shutdown_failed",
            reason=exc.__class__.__name__,
            category="observability",
        )

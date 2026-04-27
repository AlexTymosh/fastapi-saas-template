from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.config.settings import Settings
from app.core.observability import lifecycle
from tests.helpers.asyncio_runner import run_async


@dataclass
class _Recorder:
    calls: list[tuple[str, dict]]


class _FakeExporter:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs


class _FakeReader:
    def __init__(self, exporter, **kwargs) -> None:
        self.exporter = exporter
        self.kwargs = kwargs


class _FakeProvider:
    def __init__(self, *, metric_readers, resource) -> None:
        self.metric_readers = metric_readers
        self.resource = resource
        self.force_flush_calls = 0
        self.shutdown_calls = 0

    def force_flush(self):
        self.force_flush_calls += 1
        return True

    def shutdown(self):
        self.shutdown_calls += 1
        return True


@pytest.fixture(autouse=True)
def _reset_runtime() -> None:
    lifecycle._runtime.meter_provider = None
    lifecycle._runtime.initialized = False
    yield
    lifecycle._runtime.meter_provider = None
    lifecycle._runtime.initialized = False


def test_disabled_config_does_not_initialize_sdk_exporter(monkeypatch) -> None:
    settings = Settings()
    calls: list[str] = []

    monkeypatch.setattr(
        lifecycle,
        "OTLPMetricExporter",
        lambda **kwargs: calls.append("exporter"),
    )
    monkeypatch.setattr(
        lifecycle,
        "PeriodicExportingMetricReader",
        lambda *args, **kwargs: calls.append("reader"),
    )
    monkeypatch.setattr(
        lifecycle,
        "MeterProvider",
        lambda *args, **kwargs: calls.append("provider"),
    )
    monkeypatch.setattr(
        lifecycle.otel_metrics,
        "set_meter_provider",
        lambda provider: calls.append("set_provider"),
    )

    run_async(lifecycle.init_observability(settings))

    assert calls == []


def test_enabled_none_exporter_does_not_attempt_otlp(monkeypatch) -> None:
    settings = Settings(
        observability={"metrics_enabled": True, "exporter": "none"},
    )
    calls: list[str] = []

    monkeypatch.setattr(
        lifecycle,
        "OTLPMetricExporter",
        lambda **kwargs: calls.append("exporter"),
    )
    monkeypatch.setattr(
        lifecycle.otel_metrics,
        "set_meter_provider",
        lambda provider: calls.append("set_provider"),
    )

    run_async(lifecycle.init_observability(settings))

    assert calls == []


def test_enabled_otlp_initializes_exporter_reader_provider(monkeypatch) -> None:
    settings = Settings(
        app={"name": "Fallback App"},
        observability={
            "metrics_enabled": True,
            "exporter": "otlp",
            "otlp_endpoint": "http://collector:4318/v1/metrics",
            "otlp_timeout_seconds": 3.5,
            "export_interval_millis": 7000,
            "export_timeout_millis": 900,
            "service_name": "custom-service",
        },
    )

    recorder = _Recorder(calls=[])

    def _fake_exporter(**kwargs):
        recorder.calls.append(("exporter", kwargs))
        return _FakeExporter(**kwargs)

    def _fake_reader(exporter, **kwargs):
        recorder.calls.append(("reader", kwargs))
        return _FakeReader(exporter, **kwargs)

    def _fake_provider(*, metric_readers, resource):
        recorder.calls.append(("provider", {"metric_readers": metric_readers}))
        return _FakeProvider(metric_readers=metric_readers, resource=resource)

    def _fake_set_meter_provider(provider):
        recorder.calls.append(("set_meter_provider", {"provider": provider}))

    monkeypatch.setattr(lifecycle, "OTLPMetricExporter", _fake_exporter)
    monkeypatch.setattr(lifecycle, "PeriodicExportingMetricReader", _fake_reader)
    monkeypatch.setattr(lifecycle, "MeterProvider", _fake_provider)
    monkeypatch.setattr(
        lifecycle.otel_metrics,
        "set_meter_provider",
        _fake_set_meter_provider,
    )

    run_async(lifecycle.init_observability(settings))

    assert recorder.calls[0][0] == "exporter"
    assert recorder.calls[0][1]["endpoint"] == "http://collector:4318/v1/metrics"
    assert recorder.calls[0][1]["timeout"] == 3.5

    assert recorder.calls[1][0] == "reader"
    assert recorder.calls[1][1]["export_interval_millis"] == 7000
    assert recorder.calls[1][1]["export_timeout_millis"] == 900

    assert recorder.calls[2][0] == "provider"
    assert recorder.calls[3][0] == "set_meter_provider"

    provider = lifecycle._runtime.meter_provider
    assert provider is not None
    assert provider.resource.attributes[lifecycle.SERVICE_NAME] == "custom-service"


def test_service_name_falls_back_to_app_name(monkeypatch) -> None:
    settings = Settings(
        app={"name": "Fallback App"},
        observability={
            "metrics_enabled": True,
            "exporter": "otlp",
            "otlp_endpoint": "http://collector:4318/v1/metrics",
        },
    )

    monkeypatch.setattr(lifecycle, "OTLPMetricExporter", _FakeExporter)
    monkeypatch.setattr(lifecycle, "PeriodicExportingMetricReader", _FakeReader)
    monkeypatch.setattr(lifecycle, "MeterProvider", _FakeProvider)
    monkeypatch.setattr(
        lifecycle.otel_metrics,
        "set_meter_provider",
        lambda provider: None,
    )

    run_async(lifecycle.init_observability(settings))

    provider = lifecycle._runtime.meter_provider
    assert provider is not None
    assert provider.resource.attributes[lifecycle.SERVICE_NAME] == "Fallback App"


def test_missing_otlp_endpoint_fails_fast() -> None:
    settings = Settings(
        observability={"metrics_enabled": True, "exporter": "otlp"},
    )

    with pytest.raises(RuntimeError, match="OBSERVABILITY__OTLP_ENDPOINT is required"):
        run_async(lifecycle.init_observability(settings))


def test_shutdown_calls_force_flush_and_shutdown_when_initialized() -> None:
    provider = _FakeProvider(metric_readers=[], resource=object())
    lifecycle._runtime.meter_provider = provider
    lifecycle._runtime.initialized = True

    run_async(lifecycle.shutdown_observability())

    assert provider.force_flush_calls == 1
    assert provider.shutdown_calls == 1
    assert lifecycle._runtime.initialized is False


def test_shutdown_is_noop_when_provider_not_initialized() -> None:
    run_async(lifecycle.shutdown_observability())

    assert lifecycle._runtime.initialized is False


def test_shutdown_swallows_errors_and_logs_safely(monkeypatch) -> None:
    class _FailingProvider:
        def force_flush(self):
            raise RuntimeError("sensitive details")

        def shutdown(self):
            raise ValueError("sensitive details")

    class _FakeLogger:
        def __init__(self) -> None:
            self.warning_calls: list[dict] = []

        def warning(self, event: str, **kwargs) -> None:
            self.warning_calls.append({"event": event, **kwargs})

    fake_log = _FakeLogger()
    lifecycle._runtime.meter_provider = _FailingProvider()
    lifecycle._runtime.initialized = True

    monkeypatch.setattr(lifecycle, "get_logger", lambda name: fake_log)

    run_async(lifecycle.shutdown_observability())

    assert len(fake_log.warning_calls) == 2
    assert {call["operation"] for call in fake_log.warning_calls} == {
        "force_flush",
        "shutdown",
    }
    assert {call["error_type"] for call in fake_log.warning_calls} == {
        "RuntimeError",
        "ValueError",
    }


def test_repeated_init_and_shutdown_do_not_leak_state(monkeypatch) -> None:
    settings = Settings(
        observability={
            "metrics_enabled": True,
            "exporter": "otlp",
            "otlp_endpoint": "http://collector:4318/v1/metrics",
        },
    )

    set_calls: list[object] = []

    monkeypatch.setattr(lifecycle, "OTLPMetricExporter", _FakeExporter)
    monkeypatch.setattr(lifecycle, "PeriodicExportingMetricReader", _FakeReader)
    monkeypatch.setattr(lifecycle, "MeterProvider", _FakeProvider)
    monkeypatch.setattr(
        lifecycle.otel_metrics,
        "set_meter_provider",
        lambda provider: set_calls.append(provider),
    )

    run_async(lifecycle.init_observability(settings))
    run_async(lifecycle.init_observability(settings))

    assert len(set_calls) == 1

    run_async(lifecycle.shutdown_observability())
    run_async(lifecycle.shutdown_observability())

    assert lifecycle._runtime.meter_provider is None
    assert lifecycle._runtime.initialized is False

from __future__ import annotations

import pytest

from app.core.config.settings import Settings
from app.core.observability import lifecycle
from tests.helpers.asyncio_runner import run_async


class _FactoryCallRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def __call__(self, *args: object, **kwargs: object) -> object:
        self.calls.append((args, kwargs))
        return self


class _FakeProvider:
    def __init__(
        self, *, raise_force_flush: bool = False, raise_shutdown: bool = False
    ):
        self.force_flush_calls = 0
        self.shutdown_calls = 0
        self.raise_force_flush = raise_force_flush
        self.raise_shutdown = raise_shutdown

    def force_flush(self) -> None:
        self.force_flush_calls += 1
        if self.raise_force_flush:
            raise RuntimeError("flush failed")

    def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.raise_shutdown:
            raise RuntimeError("shutdown failed")


class _AsyncFakeProvider:
    def __init__(
        self, *, raise_force_flush: bool = False, raise_shutdown: bool = False
    ) -> None:
        self.force_flush_calls = 0
        self.shutdown_calls = 0
        self.raise_force_flush = raise_force_flush
        self.raise_shutdown = raise_shutdown

    async def force_flush(self) -> None:
        self.force_flush_calls += 1
        if self.raise_force_flush:
            raise RuntimeError("async flush failed")

    async def shutdown(self) -> None:
        self.shutdown_calls += 1
        if self.raise_shutdown:
            raise ValueError("async shutdown failed")


@pytest.fixture(autouse=True)
def _reset_lifecycle_state() -> None:
    lifecycle._initialized_provider = None  # noqa: SLF001
    yield
    lifecycle._initialized_provider = None  # noqa: SLF001


def test_init_observability_disabled_does_not_initialize(monkeypatch) -> None:
    settings = Settings()

    called = {"set_provider": 0}

    def _fake_set_meter_provider(provider: object) -> None:
        called["set_provider"] += 1

    monkeypatch.setattr(
        lifecycle.metrics, "set_meter_provider", _fake_set_meter_provider
    )

    run_async(lifecycle.init_observability(settings))

    assert called["set_provider"] == 0


def test_init_observability_enabled_with_exporter_none_skips_exporter(
    monkeypatch,
) -> None:
    settings = Settings.model_validate(
        {
            "observability": {
                "metrics_enabled": True,
                "exporter": "none",
            }
        }
    )

    otlp_loader_calls = {"count": 0}

    def _fake_load_otlp() -> type[object]:
        otlp_loader_calls["count"] += 1
        return object

    monkeypatch.setattr(lifecycle, "_load_otlp_metric_exporter", _fake_load_otlp)

    run_async(lifecycle.init_observability(settings))

    assert otlp_loader_calls["count"] == 0


def test_init_observability_otlp_initializes_sdk_components(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "app": {"name": "fallback-name"},
            "observability": {
                "metrics_enabled": True,
                "exporter": "otlp",
                "otlp_endpoint": "http://otel-collector:4318/v1/metrics",
                "otlp_timeout_seconds": 1.5,
                "export_interval_millis": 15000,
                "export_timeout_millis": 500,
                "service_name": "custom-service",
            },
        }
    )

    otlp_exporter = _FactoryCallRecorder()
    periodic_reader = _FactoryCallRecorder()
    resource_calls: list[str] = []
    provider_construction: list[dict[str, object]] = []
    set_meter_provider_calls: list[object] = []

    class _ProviderFactory:
        def __call__(
            self, *, metric_readers: list[object], resource: object, views: list[object]
        ) -> _FakeProvider:
            provider_construction.append(
                {
                    "metric_readers": metric_readers,
                    "resource": resource,
                    "views": views,
                }
            )
            return _FakeProvider()

    monkeypatch.setattr(lifecycle, "_load_otlp_metric_exporter", lambda: otlp_exporter)
    monkeypatch.setattr(
        lifecycle,
        "_load_periodic_exporting_metric_reader",
        lambda: periodic_reader,
    )
    monkeypatch.setattr(lifecycle, "_load_meter_provider", lambda: _ProviderFactory())
    monkeypatch.setattr(
        lifecycle,
        "_build_resource",
        lambda service_name: (
            resource_calls.append(service_name) or {"service.name": service_name}
        ),
    )
    monkeypatch.setattr(
        lifecycle.metrics,
        "set_meter_provider",
        lambda provider: set_meter_provider_calls.append(provider),
    )

    run_async(lifecycle.init_observability(settings))

    assert len(otlp_exporter.calls) == 1
    assert otlp_exporter.calls[0][1] == {
        "endpoint": "http://otel-collector:4318/v1/metrics",
        "timeout": 1.5,
    }

    assert len(periodic_reader.calls) == 1
    assert periodic_reader.calls[0][1] == {
        "export_interval_millis": 15000,
        "export_timeout_millis": 500,
    }

    assert resource_calls == ["custom-service"]
    assert len(provider_construction) == 1
    assert len(provider_construction[0]["views"]) == 1
    assert len(set_meter_provider_calls) == 1


def test_init_observability_service_name_falls_back_to_app_name(
    monkeypatch,
) -> None:
    settings = Settings.model_validate(
        {
            "app": {"name": "fallback-app"},
            "observability": {
                "metrics_enabled": True,
                "exporter": "otlp",
                "otlp_endpoint": "http://otel-collector:4318/v1/metrics",
            },
        }
    )

    monkeypatch.setattr(
        lifecycle, "_load_otlp_metric_exporter", lambda: _FactoryCallRecorder()
    )
    monkeypatch.setattr(
        lifecycle,
        "_load_periodic_exporting_metric_reader",
        lambda: _FactoryCallRecorder(),
    )
    monkeypatch.setattr(
        lifecycle, "_load_meter_provider", lambda: _FactoryCallRecorder()
    )

    service_name_calls: list[str] = []
    monkeypatch.setattr(
        lifecycle,
        "_build_resource",
        lambda service_name: service_name_calls.append(service_name) or {},
    )
    monkeypatch.setattr(lifecycle.metrics, "set_meter_provider", lambda provider: None)

    run_async(lifecycle.init_observability(settings))

    assert service_name_calls == ["fallback-app"]


def test_init_observability_fails_fast_without_otlp_endpoint() -> None:
    settings = Settings.model_validate(
        {
            "observability": {
                "metrics_enabled": True,
                "exporter": "otlp",
                "otlp_endpoint": "http://otel-collector:4318/v1/metrics",
            }
        }
    )
    settings.observability.otlp_endpoint = None

    with pytest.raises(
        RuntimeError,
        match=(
            "OBSERVABILITY__OTLP_ENDPOINT is required when "
            "OBSERVABILITY__METRICS_ENABLED=true and OBSERVABILITY__EXPORTER=otlp"
        ),
    ):
        run_async(lifecycle.init_observability(settings))


def test_shutdown_observability_calls_force_flush_and_shutdown() -> None:
    provider = _FakeProvider()
    lifecycle._initialized_provider = provider  # noqa: SLF001

    run_async(lifecycle.shutdown_observability())

    assert provider.force_flush_calls == 1
    assert provider.shutdown_calls == 1


def test_shutdown_observability_is_noop_without_provider() -> None:
    run_async(lifecycle.shutdown_observability())


def test_shutdown_observability_swallows_provider_errors(monkeypatch) -> None:
    provider = _FakeProvider(raise_force_flush=True, raise_shutdown=True)
    lifecycle._initialized_provider = provider  # noqa: SLF001

    warnings: list[tuple[str, dict[str, object]]] = []

    class _FakeLogger:
        def warning(self, event_name: str, **kwargs: object) -> None:
            warnings.append((event_name, kwargs))

    monkeypatch.setattr(lifecycle, "log", _FakeLogger())

    run_async(lifecycle.shutdown_observability())

    assert len(warnings) == 2
    assert warnings[0][0] == "observability_metrics_force_flush_failed"
    assert warnings[1][0] == "observability_metrics_shutdown_failed"
    assert warnings[0][1] == {"reason": "RuntimeError", "category": "observability"}
    assert warnings[1][1] == {"reason": "RuntimeError", "category": "observability"}


def test_shutdown_observability_awaits_async_provider_operations() -> None:
    provider = _AsyncFakeProvider()
    lifecycle._initialized_provider = provider  # noqa: SLF001

    run_async(lifecycle.shutdown_observability())

    assert provider.force_flush_calls == 1
    assert provider.shutdown_calls == 1
    assert lifecycle._initialized_provider is None  # noqa: SLF001


def test_shutdown_observability_swallows_async_provider_errors(monkeypatch) -> None:
    provider = _AsyncFakeProvider(raise_force_flush=True, raise_shutdown=True)
    lifecycle._initialized_provider = provider  # noqa: SLF001

    warnings: list[tuple[str, dict[str, object]]] = []

    class _FakeLogger:
        def warning(self, event_name: str, **kwargs: object) -> None:
            warnings.append((event_name, kwargs))

    monkeypatch.setattr(lifecycle, "log", _FakeLogger())

    run_async(lifecycle.shutdown_observability())

    assert len(warnings) == 2
    assert warnings[0][0] == "observability_metrics_force_flush_failed"
    assert warnings[1][0] == "observability_metrics_shutdown_failed"
    assert warnings[0][1] == {"reason": "RuntimeError", "category": "observability"}
    assert warnings[1][1] == {"reason": "ValueError", "category": "observability"}

    warnings_as_text = str(warnings)
    assert "async flush failed" not in warnings_as_text
    assert "async shutdown failed" not in warnings_as_text


def test_repeated_init_and_shutdown_do_not_leak_state(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "observability": {
                "metrics_enabled": True,
                "exporter": "otlp",
                "otlp_endpoint": "http://otel-collector:4318/v1/metrics",
            }
        }
    )

    monkeypatch.setattr(
        lifecycle, "_load_otlp_metric_exporter", lambda: _FactoryCallRecorder()
    )
    monkeypatch.setattr(
        lifecycle,
        "_load_periodic_exporting_metric_reader",
        lambda: _FactoryCallRecorder(),
    )
    monkeypatch.setattr(lifecycle, "_build_resource", lambda service_name: {})

    providers: list[_FakeProvider] = []

    class _ProviderFactory:
        def __call__(
            self, *, metric_readers: list[object], resource: object, views: list[object]
        ) -> _FakeProvider:
            provider = _FakeProvider()
            providers.append(provider)
            return provider

    monkeypatch.setattr(lifecycle, "_load_meter_provider", lambda: _ProviderFactory())
    monkeypatch.setattr(lifecycle.metrics, "set_meter_provider", lambda provider: None)

    run_async(lifecycle.init_observability(settings))
    run_async(lifecycle.init_observability(settings))
    run_async(lifecycle.shutdown_observability())
    run_async(lifecycle.shutdown_observability())

    assert len(providers) == 1
    assert providers[0].force_flush_calls == 1
    assert providers[0].shutdown_calls == 1


def test_init_observability_configures_http_duration_histogram_view(
    monkeypatch,
) -> None:
    settings = Settings.model_validate(
        {
            "observability": {
                "metrics_enabled": True,
                "exporter": "otlp",
                "otlp_endpoint": "http://otel-collector:4318/v1/metrics",
            }
        }
    )
    provider_construction: list[dict[str, object]] = []

    class _FakeView:
        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs

    class _FakeExplicitBucketHistogramAggregation:
        def __init__(self, boundaries: tuple[float, ...]) -> None:
            self.boundaries = boundaries

    class _ProviderFactory:
        def __call__(
            self, *, metric_readers: list[object], resource: object, views: list[object]
        ) -> _FakeProvider:
            provider_construction.append(
                {
                    "metric_readers": metric_readers,
                    "resource": resource,
                    "views": views,
                }
            )
            return _FakeProvider()

    monkeypatch.setattr(
        lifecycle, "_load_otlp_metric_exporter", lambda: _FactoryCallRecorder()
    )
    monkeypatch.setattr(
        lifecycle,
        "_load_periodic_exporting_metric_reader",
        lambda: _FactoryCallRecorder(),
    )
    monkeypatch.setattr(lifecycle, "_load_meter_provider", lambda: _ProviderFactory())
    monkeypatch.setattr(
        lifecycle,
        "_load_metric_views",
        lambda: (_FakeView, _FakeExplicitBucketHistogramAggregation),
    )
    monkeypatch.setattr(lifecycle, "_build_resource", lambda service_name: {})
    monkeypatch.setattr(lifecycle.metrics, "set_meter_provider", lambda provider: None)

    run_async(lifecycle.init_observability(settings))

    assert len(provider_construction) == 1
    views = provider_construction[0]["views"]
    assert isinstance(views, list)
    assert len(views) == 1
    view = views[0]
    assert isinstance(view, _FakeView)
    assert view.kwargs["instrument_name"] == "http.server.request.duration"
    aggregation = view.kwargs["aggregation"]
    assert isinstance(aggregation, _FakeExplicitBucketHistogramAggregation)
    assert aggregation.boundaries == lifecycle.HTTP_SERVER_DURATION_BUCKETS


def test_init_observability_sets_global_meter_provider_only_once(monkeypatch) -> None:
    settings = Settings.model_validate(
        {
            "observability": {
                "metrics_enabled": True,
                "exporter": "otlp",
                "otlp_endpoint": "http://otel-collector:4318/v1/metrics",
            }
        }
    )
    set_meter_provider_calls: list[object] = []

    class _ProviderFactory:
        def __call__(
            self, *, metric_readers: list[object], resource: object, views: list[object]
        ) -> _FakeProvider:
            return _FakeProvider()

    monkeypatch.setattr(
        lifecycle, "_load_otlp_metric_exporter", lambda: _FactoryCallRecorder()
    )
    monkeypatch.setattr(
        lifecycle,
        "_load_periodic_exporting_metric_reader",
        lambda: _FactoryCallRecorder(),
    )
    monkeypatch.setattr(lifecycle, "_load_meter_provider", lambda: _ProviderFactory())
    monkeypatch.setattr(lifecycle, "_build_resource", lambda service_name: {})
    monkeypatch.setattr(
        lifecycle.metrics,
        "set_meter_provider",
        lambda provider: set_meter_provider_calls.append(provider),
    )

    run_async(lifecycle.init_observability(settings))
    run_async(lifecycle.init_observability(settings))

    assert len(set_meter_provider_calls) == 1

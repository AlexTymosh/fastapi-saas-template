from __future__ import annotations

from app.core.observability import safety


class _LogCapture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def warning(self, event_name: str, **kwargs: object) -> None:
        self.calls.append((event_name, kwargs))


class _FailureCapture:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    def __call__(self, metric_name: str, metric_event: str, reason: str) -> None:
        self.calls.append((metric_name, metric_event, reason))


class _RaisingLogger:
    def warning(self, event_name: str, **kwargs: object) -> None:
        raise RuntimeError("logger backend down")


def _raise_runtime_error() -> None:
    raise RuntimeError("metrics backend down")


def test_safety_logs_first_failure_then_suppresses_within_window(monkeypatch) -> None:
    logger = _LogCapture()
    failures = _FailureCapture()
    monotonic_values = iter([10.0, 20.0])

    monkeypatch.setattr(safety, "log", logger)
    monkeypatch.setattr(safety, "_last_metrics_failure_log_at", {})
    monkeypatch.setattr(safety.time, "monotonic", lambda: next(monotonic_values))

    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.requests.total",
        metric_event="http_request",
        on_failure=failures,
    )
    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.requests.total",
        metric_event="http_request",
        on_failure=failures,
    )

    assert len(logger.calls) == 1
    assert len(failures.calls) == 2


def test_safety_logs_again_after_suppression_window(monkeypatch) -> None:
    logger = _LogCapture()
    monotonic_values = iter([10.0, 80.0])

    monkeypatch.setattr(safety, "log", logger)
    monkeypatch.setattr(safety, "_last_metrics_failure_log_at", {})
    monkeypatch.setattr(safety.time, "monotonic", lambda: next(monotonic_values))

    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.requests.total",
        metric_event="http_request",
    )
    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.requests.total",
        metric_event="http_request",
    )

    assert len(logger.calls) == 2


def test_safety_tracks_different_failure_keys_separately(monkeypatch) -> None:
    logger = _LogCapture()

    monkeypatch.setattr(safety, "log", logger)
    monkeypatch.setattr(safety, "_last_metrics_failure_log_at", {})
    monkeypatch.setattr(safety.time, "monotonic", lambda: 10.0)

    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.requests.total",
        metric_event="http_request",
    )
    safety.safely_record_observability(
        lambda: (_ for _ in ()).throw(ValueError("bad value")),
        metric_name="http.server.requests.total",
        metric_event="http_request",
    )
    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.errors.total",
        metric_event="http_error",
    )

    assert len(logger.calls) == 3


def test_safety_does_not_raise_when_logger_fails(monkeypatch) -> None:
    monkeypatch.setattr(safety, "log", _RaisingLogger())
    monkeypatch.setattr(safety, "_last_metrics_failure_log_at", {})

    safety.safely_record_observability(
        _raise_runtime_error,
        metric_name="http.server.requests.total",
        metric_event="http_request",
    )

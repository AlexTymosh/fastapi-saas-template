from __future__ import annotations

from dataclasses import dataclass

from starlette.requests import Request

from app.core.observability import metrics


class FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str] | None]] = []

    def add(self, value: int, attributes: dict[str, str] | None = None) -> None:
        self.calls.append((value, attributes))


class FakeHistogram:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, str] | None]] = []

    def record(self, value: float, attributes: dict[str, str] | None = None) -> None:
        self.calls.append((value, attributes))


@dataclass
class _Route:
    path: str


def _build_request(scope_overrides: dict[str, object] | None = None) -> Request:
    scope: dict[str, object] = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "scheme": "https",
        "path": "/api/v1/organisations/0d24d25d-3386-4d85-bf22-5c93973bb1bf/invites",
        "raw_path": (
            b"/api/v1/organisations/0d24d25d-3386-4d85-bf22-5c93973bb1bf/invites"
        ),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("testserver", 443),
    }
    if scope_overrides:
        scope.update(scope_overrides)
    return Request(scope=scope)


def test_record_rate_limit_decision_uses_only_allowed_attributes(monkeypatch) -> None:
    fake_counter = FakeCounter()
    monkeypatch.setattr(metrics, "rate_limit_requests_total", fake_counter)

    metrics.record_rate_limit_decision(
        policy_name="invite_accept",
        result="allowed",
        identifier_kind="user",
    )

    assert fake_counter.calls == [
        (
            1,
            {
                "rate_limit.policy": "invite_accept",
                "rate_limit.result": "allowed",
                "rate_limit.identifier_kind": "user",
            },
        )
    ]


def test_record_rate_limit_backend_error_uses_only_allowed_attributes(
    monkeypatch,
) -> None:
    fake_counter = FakeCounter()
    monkeypatch.setattr(metrics, "rate_limit_backend_errors_total", fake_counter)

    metrics.record_rate_limit_backend_error(
        policy_name="invite_create",
        identifier_kind="user",
        error_type="RuntimeError",
    )

    assert fake_counter.calls == [
        (
            1,
            {
                "rate_limit.policy": "invite_create",
                "rate_limit.identifier_kind": "user",
                "error.type": "RuntimeError",
            },
        )
    ]


def test_record_rate_limit_check_duration_uses_only_allowed_attributes(
    monkeypatch,
) -> None:
    fake_histogram = FakeHistogram()
    monkeypatch.setattr(metrics, "rate_limit_check_duration", fake_histogram)

    metrics.record_rate_limit_check_duration(
        policy_name="invite_accept",
        result="blocked",
        identifier_kind="user",
        duration_seconds=0.011,
    )

    assert fake_histogram.calls == [
        (
            0.011,
            {
                "rate_limit.policy": "invite_accept",
                "rate_limit.result": "blocked",
                "rate_limit.identifier_kind": "user",
            },
        )
    ]


def test_helpers_do_not_emit_forbidden_high_cardinality_attribute_keys() -> None:
    decisions = {
        "rate_limit.policy",
        "rate_limit.result",
        "rate_limit.identifier_kind",
    }
    durations = {
        "rate_limit.policy",
        "rate_limit.result",
        "rate_limit.identifier_kind",
    }
    backend_errors = {
        "rate_limit.policy",
        "rate_limit.identifier_kind",
        "error.type",
    }

    assert decisions.isdisjoint(metrics.FORBIDDEN_METRIC_ATTRIBUTE_KEYS)
    assert durations.isdisjoint(metrics.FORBIDDEN_METRIC_ATTRIBUTE_KEYS)
    assert backend_errors.isdisjoint(metrics.FORBIDDEN_METRIC_ATTRIBUTE_KEYS)


def test_metrics_helpers_are_safe_without_sdk() -> None:
    metrics.record_rate_limit_decision(
        policy_name="invite_accept",
        result="allowed",
        identifier_kind="user",
    )
    metrics.record_rate_limit_backend_error(
        policy_name="invite_accept",
        identifier_kind="user",
        error_type="RuntimeError",
    )
    metrics.record_rate_limit_check_duration(
        policy_name="invite_accept",
        result="allowed",
        identifier_kind="user",
        duration_seconds=0.001,
    )


def test_get_route_template_returns_route_path_template() -> None:
    request = _build_request(
        scope_overrides={
            "route": _Route(path="/api/v1/organisations/{organisation_id}/invites")
        }
    )

    assert (
        metrics.get_route_template(request)
        == "/api/v1/organisations/{organisation_id}/invites"
    )


def test_get_route_template_returns_unknown_when_route_is_missing() -> None:
    request = _build_request()

    assert metrics.get_route_template(request) == "unknown"


def test_get_route_template_never_uses_raw_url_path() -> None:
    request = _build_request(
        scope_overrides={
            "path": "/api/v1/organisations/aad8d0fb-c9b3-40a7-941d-4a9bf6764bfd/invites"
        }
    )

    assert metrics.get_route_template(request) == "unknown"

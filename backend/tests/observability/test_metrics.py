from __future__ import annotations

from app.core.observability import metrics


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.calls.append((value, attributes))


class _FakeHistogram:
    def __init__(self) -> None:
        self.calls: list[tuple[float, dict[str, str]]] = []

    def record(self, value: float, attributes: dict[str, str]) -> None:
        self.calls.append((value, attributes))


def test_record_rate_limit_request_uses_expected_attributes(monkeypatch) -> None:
    fake_counter = _FakeCounter()
    monkeypatch.setattr(metrics, "_rate_limit_requests_total", fake_counter)

    metrics.record_rate_limit_request(
        policy_name="invite_create",
        result="allowed",
        identifier_kind="user",
    )

    assert fake_counter.calls == [
        (
            1,
            {
                "rate_limit.policy": "invite_create",
                "rate_limit.result": "allowed",
                "rate_limit.identifier_kind": "user",
            },
        )
    ]


def test_record_rate_limit_backend_error_uses_expected_attributes(monkeypatch) -> None:
    fake_counter = _FakeCounter()
    monkeypatch.setattr(metrics, "_rate_limit_backend_errors_total", fake_counter)

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


def test_record_rate_limit_check_duration_uses_expected_attributes(monkeypatch) -> None:
    fake_histogram = _FakeHistogram()
    monkeypatch.setattr(metrics, "_rate_limit_check_duration", fake_histogram)

    metrics.record_rate_limit_check_duration(
        policy_name="invite_create",
        result="blocked",
        identifier_kind="user",
        duration_seconds=0.015,
    )

    assert fake_histogram.calls == [
        (
            0.015,
            {
                "rate_limit.policy": "invite_create",
                "rate_limit.result": "blocked",
                "rate_limit.identifier_kind": "user",
            },
        )
    ]

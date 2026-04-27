from __future__ import annotations

import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache


def test_observability_settings_defaults_are_safe_noop() -> None:
    reset_settings_cache()
    settings = get_settings()

    assert settings.observability.metrics_enabled is False
    assert settings.observability.exporter == "none"
    assert settings.observability.otlp_endpoint is None
    assert settings.observability.otlp_timeout_seconds > 0
    assert settings.observability.export_interval_millis > 0
    assert settings.observability.export_timeout_millis > 0

    reset_settings_cache()


@pytest.mark.parametrize(
    ("env_name", "value"),
    [
        ("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "0"),
        ("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "-1"),
        ("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "0"),
        ("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "-100"),
        ("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "0"),
        ("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "-100"),
    ],
)
def test_observability_settings_reject_non_positive_tuning_values(
    monkeypatch,
    env_name: str,
    value: str,
) -> None:
    monkeypatch.setenv(env_name, value)

    reset_settings_cache()
    with pytest.raises(ValueError):
        get_settings()

    reset_settings_cache()


def test_observability_settings_allow_enabled_with_exporter_none(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "none")
    monkeypatch.delenv("OBSERVABILITY__OTLP_ENDPOINT", raising=False)

    reset_settings_cache()
    settings = get_settings()

    assert settings.observability.metrics_enabled is True
    assert settings.observability.exporter == "none"
    assert settings.observability.otlp_endpoint is None

    reset_settings_cache()


def test_observability_settings_require_endpoint_for_otlp_exporter(monkeypatch) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.setenv("OBSERVABILITY__OTLP_ENDPOINT", "")

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match=(
            "OBSERVABILITY__OTLP_ENDPOINT is required when "
            "OBSERVABILITY__METRICS_ENABLED=true and OBSERVABILITY__EXPORTER=otlp"
        ),
    ):
        get_settings()

    reset_settings_cache()

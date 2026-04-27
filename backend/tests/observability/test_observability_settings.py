import pytest

from app.core.config.settings import get_settings
from tests.helpers.settings import reset_settings_cache


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "0"),
        ("OBSERVABILITY__OTLP_TIMEOUT_SECONDS", "-1"),
        ("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "0"),
        ("OBSERVABILITY__EXPORT_INTERVAL_MILLIS", "-1"),
        ("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "0"),
        ("OBSERVABILITY__EXPORT_TIMEOUT_MILLIS", "-1"),
    ],
)
def test_observability_timing_values_must_be_positive(
    monkeypatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)

    reset_settings_cache()
    with pytest.raises(
        ValueError,
        match="Observability timing values must be positive",
    ):
        get_settings()

    reset_settings_cache()


def test_observability_defaults_are_safe_noop() -> None:
    reset_settings_cache()
    settings = get_settings()

    assert settings.observability.metrics_enabled is False
    assert settings.observability.exporter == "none"
    assert settings.observability.otlp_endpoint is None
    assert settings.observability.otlp_timeout_seconds > 0
    assert settings.observability.export_interval_millis > 0
    assert settings.observability.export_timeout_millis > 0

    reset_settings_cache()


def test_observability_enabled_with_exporter_none_does_not_require_endpoint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "none")
    monkeypatch.delenv("OBSERVABILITY__OTLP_ENDPOINT", raising=False)

    reset_settings_cache()
    settings = get_settings()

    assert settings.observability.metrics_enabled is True
    assert settings.observability.exporter == "none"
    assert settings.observability.otlp_endpoint is None

    reset_settings_cache()

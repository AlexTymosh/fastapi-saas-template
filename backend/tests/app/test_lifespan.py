import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.settings import reset_settings_cache


def _parse_json_lines(output: str) -> list[dict]:
    records: list[dict] = []

    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue

        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    return records


def test_lifespan_logs_startup_and_shutdown(monkeypatch) -> None:
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("LOGGING__LEVEL", "INFO")
    reset_settings_cache()

    stream = io.StringIO()

    with patch("sys.stdout", stream):
        app = create_app()

        with TestClient(app) as client:
            response = client.get("/api/v1/health/live")
            assert response.status_code == 200

    output = stream.getvalue()
    records = _parse_json_lines(output)

    assert records, f"No logs captured. Output: {output}"

    events = [record.get("event") for record in records]

    assert "app_started" in events
    assert "app_stopped" in events


def test_lifespan_does_not_require_redis_when_rate_limiting_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.delenv("REDIS__URL", raising=False)
    reset_settings_cache()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_lifespan_fails_fast_when_rate_limiting_disabled_in_secure_environment(
    monkeypatch,
    environment: str,
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", environment)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ALLOW_DISABLED_IN_PROD", "false")
    reset_settings_cache()

    app = create_app()
    with pytest.raises(
        RuntimeError,
        match=(
            "RATE_LIMITING__ENABLED=false is not allowed in staging/prod unless "
            "RATE_LIMITING__ALLOW_DISABLED_IN_PROD=true"
        ),
    ):
        with TestClient(app):
            pass


@pytest.mark.parametrize("environment", ["staging", "prod"])
def test_lifespan_allows_disabled_rate_limiting_with_explicit_bypass_and_logs_warning(
    monkeypatch,
    environment: str,
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", environment)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ALLOW_DISABLED_IN_PROD", "true")
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    reset_settings_cache()

    stream = io.StringIO()
    with patch("sys.stdout", stream):
        app = create_app()
        with TestClient(app) as client:
            response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    records = _parse_json_lines(stream.getvalue())
    warning_records = [
        record
        for record in records
        if record.get("event") == "rate_limiting_disabled_in_secure_environment"
    ]
    assert warning_records
    assert warning_records[0]["environment"] == environment
    assert warning_records[0]["category"] == "security"
    assert warning_records[0]["allow_disabled_in_prod"] is True


def test_lifespan_test_environment_allows_disabled_rate_limiting(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "test")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.setenv("RATE_LIMITING__ALLOW_DISABLED_IN_PROD", "false")
    reset_settings_cache()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200


def test_lifespan_fails_fast_when_rate_limiting_enabled_without_redis(
    monkeypatch,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.delenv("REDIS__URL", raising=False)
    reset_settings_cache()

    app = create_app()
    with pytest.raises(
        RuntimeError,
        match="REDIS__URL is required when RATE_LIMITING__ENABLED=true",
    ):
        with TestClient(app):
            pass


def test_lifespan_prod_enabled_rate_limiting_still_requires_redis(
    monkeypatch,
) -> None:
    monkeypatch.setenv("APP__ENVIRONMENT", "prod")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.delenv("REDIS__URL", raising=False)
    reset_settings_cache()

    app = create_app()
    with pytest.raises(
        RuntimeError,
        match="REDIS__URL is required when RATE_LIMITING__ENABLED=true",
    ):
        with TestClient(app):
            pass


def test_lifespan_default_startup_does_not_require_otlp_endpoint(monkeypatch) -> None:
    monkeypatch.delenv("OBSERVABILITY__OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OBSERVABILITY__METRICS_ENABLED", raising=False)
    monkeypatch.delenv("OBSERVABILITY__EXPORTER", raising=False)
    reset_settings_cache()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200


def test_lifespan_fails_fast_when_observability_otlp_missing_endpoint(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "otlp")
    monkeypatch.delenv("OBSERVABILITY__OTLP_ENDPOINT", raising=False)
    reset_settings_cache()

    with pytest.raises(
        ValueError,
        match=(
            "OBSERVABILITY__OTLP_ENDPOINT is required when "
            "OBSERVABILITY__METRICS_ENABLED=true and OBSERVABILITY__EXPORTER=otlp"
        ),
    ):
        create_app()


def test_lifespan_starts_when_observability_enabled_with_exporter_none(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "none")
    monkeypatch.delenv("OBSERVABILITY__OTLP_ENDPOINT", raising=False)
    reset_settings_cache()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200


def test_lifespan_observability_does_not_change_rate_limiter_defaults(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OBSERVABILITY__METRICS_ENABLED", "true")
    monkeypatch.setenv("OBSERVABILITY__EXPORTER", "none")
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")
    monkeypatch.delenv("REDIS__URL", raising=False)
    reset_settings_cache()

    app = create_app()
    with TestClient(app) as client:
        response = client.get("/api/v1/health/live")

    assert response.status_code == 200

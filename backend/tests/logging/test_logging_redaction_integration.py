import io
import json
from unittest.mock import patch

from app.core.config.settings import get_settings
from app.core.context import request_id_ctx
from app.core.logging.factory import configure_logging, get_logger

settings = get_settings()


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


def test_logging_output_redacts_sensitive_fields(monkeypatch) -> None:
    stream = io.StringIO()

    monkeypatch.setattr(settings.logging, "as_json", True)
    monkeypatch.setattr(settings.logging, "level", "INFO")

    with patch("sys.stdout", stream):
        configure_logging(
            log_level=settings.logging.level,
            log_json=settings.logging.as_json,
            service_name="test-service",
            environment="test",
            version="0.1.0",
        )

        token = request_id_ctx.set("req-123")
        try:
            log = get_logger("test.logger")

            log.info(
                "user_action",
                password="secret123",
                token="abc123",
                authorization="Bearer xyz",
                cookie="session=123",
                api_key="key-123",
                email="alex@example.com",
                payload={
                    "email": "nested@example.com",
                    "token": "nested-token",
                    "profile": {"password": "nested-secret"},
                },
            )
        finally:
            request_id_ctx.reset(token)

    records = _parse_json_lines(stream.getvalue())

    assert records, f"No logs captured. Output: {stream.getvalue()}"

    record = records[-1]

    # --- verify sensitive fields are redacted ---
    assert record["password"] == "[REDACTED]"
    assert record["token"] == "[REDACTED]"
    assert record["authorization"] == "[REDACTED]"
    assert record["cookie"] == "[REDACTED]"
    assert record["api_key"] == "[REDACTED]"

    # --- verify email is masked ---
    assert record["email"] != "alex@example.com"
    assert record["email"].endswith("@example.com")

    # --- verify nested structures are sanitized ---
    payload = record["payload"]

    assert payload["token"] == "[REDACTED]"
    assert payload["profile"]["password"] == "[REDACTED]"

    assert payload["email"] != "nested@example.com"
    assert payload["email"].endswith("@example.com")

    # --- verify core metadata ---
    assert record["request_id"] == "req-123"
    assert record["event"] == "user_action"

    # --- ensure no raw sensitive values leaked to output ---
    raw_output = stream.getvalue()

    assert "secret123" not in raw_output
    assert "nested-secret" not in raw_output
    assert "abc123" not in raw_output
    assert "nested-token" not in raw_output

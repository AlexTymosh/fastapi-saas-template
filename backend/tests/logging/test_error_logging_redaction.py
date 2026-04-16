import io
import json
from unittest.mock import patch

from fastapi import APIRouter, Request
from fastapi.testclient import TestClient

from app.core.config.settings import get_settings
from app.main import create_app

settings = get_settings()


def build_test_client(*, raise_server_exceptions: bool = False) -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.post("/test/error-with-sensitive-data")
    async def error_with_sensitive_data(request: Request) -> None:
        payload = await request.json()

        raise RuntimeError(
            f"boom password={payload.get('password')} token={payload.get('token')}"
        )

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


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


def test_failed_request_logs_error_without_leaking_sensitive_values(
    monkeypatch,
) -> None:
    stream = io.StringIO()

    monkeypatch.setattr(settings.logging, "as_json", True)
    monkeypatch.setattr(settings.logging, "level", "INFO")

    with patch("sys.stdout", stream):
        client = build_test_client()

        response = client.post(
            "/test/error-with-sensitive-data",
            headers={"X-Request-ID": "req-500-redaction"},
            json={
                "email": "alex@example.com",
                "password": "secret123",
                "token": "abc123",
            },
        )

    assert response.status_code == 500

    output = stream.getvalue()
    records = _parse_json_lines(output)

    assert records, f"No logs captured. Output: {output}"

    error_logs = [r for r in records if r.get("event") == "request_failed"]
    assert error_logs, f"request_failed log was not emitted. Output: {output}"

    record = error_logs[-1]
    assert record["category"] == "application"
    assert record["method"] == "POST"
    assert record["path"] == "/test/error-with-sensitive-data"
    assert record["status_code"] == 500
    assert record["request_id"] == "req-500-redaction"
    assert "duration_ms" in record

    # В итоговом log output не должно быть исходных секретов.
    assert "secret123" not in output
    assert "abc123" not in output

    # Email тоже не должен утечь как есть.
    assert "alex@example.com" not in output

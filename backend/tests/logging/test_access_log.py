import io
import json
from unittest.mock import patch

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.main import create_app


def build_test_client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.get("/test/logged")
    async def test_logged() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/test/logged-error")
    async def test_logged_error() -> None:
        raise RuntimeError("boom")

    @router.post("/api/v1/invites/{token}/accept")
    async def legacy_invite_accept(token: str) -> dict[str, str]:
        return {"token": token}

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


def test_access_log_middleware_logs_success_request(monkeypatch) -> None:
    stream = io.StringIO()
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("LOGGING__LEVEL", "INFO")

    with patch("sys.stdout", stream):
        client = build_test_client()
        response = client.get("/test/logged", headers={"X-Request-ID": "req-123"})

    assert response.status_code == 200

    records = _parse_json_lines(stream.getvalue())
    access_logs = [r for r in records if r.get("event") == "request_completed"]

    assert (
        access_logs
    ), f"request_completed log was not emitted. Output: {stream.getvalue()}"

    record = access_logs[-1]
    assert record["category"] == "application"
    assert record["method"] == "GET"
    assert record["path"] == "/test/logged"
    assert record["status_code"] == 200
    assert "duration_ms" in record
    assert record["request_id"] == "req-123"


def test_access_log_middleware_logs_failed_request(monkeypatch) -> None:
    stream = io.StringIO()
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("LOGGING__LEVEL", "INFO")

    with patch("sys.stdout", stream):
        client = build_test_client(raise_server_exceptions=False)
        response = client.get(
            "/test/logged-error",
            headers={"X-Request-ID": "req-500"},
        )

    assert response.status_code == 500

    records = _parse_json_lines(stream.getvalue())
    error_logs = [r for r in records if r.get("event") == "request_failed"]

    assert (
        error_logs
    ), f"request_failed log was not emitted. Output: {stream.getvalue()}"

    record = error_logs[-1]
    assert record["category"] == "application"
    assert record["method"] == "GET"
    assert record["path"] == "/test/logged-error"
    assert record["status_code"] == 500
    assert "duration_ms" in record
    assert record["request_id"] == "req-500"


def test_access_log_middleware_redacts_invite_token_from_path(monkeypatch) -> None:
    stream = io.StringIO()
    monkeypatch.setenv("LOGGING__AS_JSON", "true")
    monkeypatch.setenv("LOGGING__LEVEL", "INFO")

    raw_token = "secret-invite-token-123"

    with patch("sys.stdout", stream):
        client = build_test_client()
        response = client.post(
            f"/api/v1/invites/{raw_token}/accept",
            headers={"X-Request-ID": "req-redacted"},
        )

    assert response.status_code == 200

    output = stream.getvalue()
    records = _parse_json_lines(output)
    access_logs = [r for r in records if r.get("event") == "request_completed"]

    assert access_logs, f"request_completed log was not emitted. Output: {output}"

    record = access_logs[-1]
    assert record["path"] == "/api/v1/invites/[redacted]/accept"
    assert raw_token not in output

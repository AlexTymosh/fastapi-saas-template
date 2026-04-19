import io
import json
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.core.config.settings import get_settings
from app.main import create_app


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
    get_settings.cache_clear()

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

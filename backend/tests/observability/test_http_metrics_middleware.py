from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import FastAPI, WebSocket
from fastapi.responses import PlainTextResponse
from fastapi.testclient import TestClient

from app.core.observability.middleware import HttpMetricsMiddleware


class _CallRecorder:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def __call__(self, **kwargs: object) -> None:
        self.calls.append(kwargs)


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(HttpMetricsMiddleware)

    @app.get("/api/v1/test/success")
    async def success() -> dict[str, str]:
        return {"ok": "true"}

    @app.get("/api/v1/test/error-response")
    async def error_response() -> PlainTextResponse:
        return PlainTextResponse("boom", status_code=500)

    @app.get("/api/v1/test/exception")
    async def exception() -> None:
        raise RuntimeError("boom")

    @app.get("/api/v1/test/not-found", status_code=404)
    async def not_found() -> PlainTextResponse:
        return PlainTextResponse("not found", status_code=404)

    @app.get("/api/v1/test/items/{item_id}")
    async def item(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @app.get("/api/v1/test/items/{item_id}/exception")
    async def item_exception(item_id: str) -> None:
        raise RuntimeError("boom")

    @app.websocket("/ws")
    async def ws_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.close()

    return app


def test_success_request_records_rate_and_duration_only(monkeypatch) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error", error_calls
    )

    client = TestClient(_build_app())
    response = client.get("/api/v1/test/success")

    assert response.status_code == 200
    assert len(request_calls.calls) == 1
    assert len(duration_calls.calls) == 1
    assert len(error_calls.calls) == 0


def test_500_response_records_request_duration_and_error(monkeypatch) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error", error_calls
    )

    client = TestClient(_build_app())
    response = client.get("/api/v1/test/error-response")

    assert response.status_code == 500
    assert len(request_calls.calls) == 1
    assert len(duration_calls.calls) == 1
    assert len(error_calls.calls) == 1
    assert error_calls.calls[0]["error_type"] == "http_5xx"


def test_unhandled_exception_records_duration_and_error_and_reraises(
    monkeypatch,
) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error", error_calls
    )

    client = TestClient(_build_app())

    with pytest.raises(RuntimeError, match="boom"):
        client.get("/api/v1/test/exception")

    assert len(request_calls.calls) == 1
    assert len(duration_calls.calls) == 1
    assert len(error_calls.calls) == 1
    assert error_calls.calls[0]["error_type"] == "RuntimeError"


def test_route_label_uses_route_template_only(monkeypatch) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        error_calls,
    )

    client = TestClient(_build_app())
    item_id = str(uuid4())
    response = client.get(f"/api/v1/test/items/{item_id}")

    assert response.status_code == 200
    assert len(request_calls.calls) == 1
    recorded_route = request_calls.calls[0]["route"]
    assert recorded_route == "/api/v1/test/items/{item_id}"
    captured_payload = {
        "request": request_calls.calls,
        "duration": duration_calls.calls,
        "error": error_calls.calls,
    }
    assert item_id not in str(captured_payload)


def test_exception_route_uses_route_template_only(monkeypatch) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        error_calls,
    )

    client = TestClient(_build_app())
    item_id = str(uuid4())

    with pytest.raises(RuntimeError, match="boom"):
        client.get(f"/api/v1/test/items/{item_id}/exception")

    assert len(request_calls.calls) == 1
    assert len(duration_calls.calls) == 1
    assert len(error_calls.calls) == 1
    assert request_calls.calls[0]["route"] == "/api/v1/test/items/{item_id}/exception"
    captured_payload = {
        "request": request_calls.calls,
        "duration": duration_calls.calls,
        "error": error_calls.calls,
    }
    assert item_id not in str(captured_payload)


def test_missing_route_template_falls_back_to_unknown(monkeypatch) -> None:
    request_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )

    app = FastAPI()
    app.add_middleware(HttpMetricsMiddleware)

    client = TestClient(app)
    response = client.get("/no-route-handler")

    assert response.status_code == 404
    assert len(request_calls.calls) == 1
    assert request_calls.calls[0]["route"] == "unknown"


def test_non_http_scope_passes_without_metrics(monkeypatch) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error", error_calls
    )

    app = _build_app()
    client = TestClient(app)
    with client.websocket_connect("/ws"):
        pass

    assert len(request_calls.calls) == 0
    assert len(duration_calls.calls) == 0
    assert len(error_calls.calls) == 0


def test_4xx_response_does_not_record_error(monkeypatch) -> None:
    request_calls = _CallRecorder()
    duration_calls = _CallRecorder()
    error_calls = _CallRecorder()
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        request_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        duration_calls,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error", error_calls
    )

    client = TestClient(_build_app())
    response = client.get("/api/v1/test/not-found")

    assert response.status_code == 404
    assert len(request_calls.calls) == 1
    assert len(duration_calls.calls) == 1
    assert len(error_calls.calls) == 0

from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi import APIRouter, Response
from fastapi.testclient import TestClient

from app.core.observability.middleware import HttpMetricsMiddleware
from app.main import create_app


def _build_client_with_router() -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.get("/api/v1/test/ok")
    async def _ok() -> dict[str, str]:
        return {"status": "ok"}

    @router.get("/api/v1/test/error-500")
    async def _error_500() -> Response:
        return Response(status_code=500)

    @router.get("/api/v1/test/exception")
    async def _exception() -> dict[str, str]:
        raise RuntimeError("boom")

    @router.get("/api/v1/test/items/{item_id}")
    async def _items(item_id: str) -> dict[str, str]:
        return {"item_id": item_id}

    @router.get("/api/v1/test/not-found")
    async def _not_found() -> Response:
        return Response(status_code=404)

    app.include_router(router)
    return TestClient(app)


def test_success_records_request_and_duration(monkeypatch) -> None:
    client = _build_client_with_router()
    calls: dict[str, list[dict[str, object]]] = {
        "request": [],
        "duration": [],
        "error": [],
    }
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: calls["request"].append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        lambda **kwargs: calls["duration"].append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        lambda **kwargs: calls["error"].append(kwargs),
    )

    response = client.get("/api/v1/test/ok")

    assert response.status_code == 200
    assert len(calls["request"]) == 1
    assert len(calls["duration"]) == 1
    assert calls["error"] == []


def test_500_response_records_request_duration_and_error(monkeypatch) -> None:
    client = _build_client_with_router()
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        lambda **kwargs: calls.append(kwargs),
    )

    response = client.get("/api/v1/test/error-500")

    assert response.status_code == 500
    assert len(calls) == 1
    assert calls[0]["error_type"] == "http_5xx"


def test_unhandled_exception_records_and_reraises(monkeypatch) -> None:
    client = _build_client_with_router()
    duration_calls: list[dict[str, object]] = []
    error_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        lambda **kwargs: duration_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        lambda **kwargs: error_calls.append(kwargs),
    )

    with pytest.raises(RuntimeError):
        client.get("/api/v1/test/exception")

    assert len(duration_calls) == 1
    assert len(error_calls) == 1
    assert error_calls[0]["error_type"] == "RuntimeError"


def test_route_label_uses_route_template(monkeypatch) -> None:
    client = _build_client_with_router()
    request_calls: list[dict[str, object]] = []
    concrete_item_id = str(uuid4())
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: request_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        lambda **kwargs: None,
    )

    response = client.get(f"/api/v1/test/items/{concrete_item_id}")

    assert response.status_code == 200
    assert len(request_calls) == 1
    assert request_calls[0]["route"] == "/api/v1/test/items/{item_id}"
    assert concrete_item_id not in str(request_calls[0])


def test_missing_route_uses_unknown_label(monkeypatch) -> None:
    captured_routes: list[str] = []
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: captured_routes.append(str(kwargs["route"])),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        lambda **kwargs: None,
    )

    async def app(scope, receive, send) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    middleware = HttpMetricsMiddleware(app)
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": f"/api/v1/test/items/{uuid4()}",
        "raw_path": b"/api/v1/test/items/value",
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 8000),
        "server": ("testserver", 80),
    }

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    sent_messages = []

    async def send(message):
        sent_messages.append(message)

    import asyncio

    asyncio.run(middleware(scope, receive, send))

    assert captured_routes == ["unknown"]
    assert str(scope["path"]) not in captured_routes
    assert len(sent_messages) == 2


def test_non_http_scope_passes_through_without_metrics(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: calls.append(kwargs),
    )

    events: list[str] = []

    async def app(scope, receive, send) -> None:
        events.append(scope["type"])

    middleware = HttpMetricsMiddleware(app)

    import asyncio

    asyncio.run(
        middleware(
            {"type": "websocket"},
            lambda: {"type": "websocket.receive"},
            lambda message: None,
        )
    )

    assert events == ["websocket"]
    assert calls == []


def test_4xx_response_is_not_counted_as_error(monkeypatch) -> None:
    client = _build_client_with_router()
    error_calls: list[dict[str, object]] = []
    request_calls: list[dict[str, object]] = []
    duration_calls: list[dict[str, object]] = []
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request",
        lambda **kwargs: request_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_request_duration",
        lambda **kwargs: duration_calls.append(kwargs),
    )
    monkeypatch.setattr(
        "app.core.observability.middleware.record_http_error",
        lambda **kwargs: error_calls.append(kwargs),
    )

    response = client.get("/api/v1/test/not-found")

    assert response.status_code == 404
    assert len(request_calls) == 1
    assert len(duration_calls) == 1
    assert error_calls == []

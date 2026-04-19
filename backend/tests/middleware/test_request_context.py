from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.context import get_request_id
from app.core.middleware.request_context import RequestContextMiddleware
from app.main import create_app


def build_test_client() -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.get("/test/request-id")
    async def test_request_id() -> dict[str, str]:
        return {"request_id": get_request_id()}

    app.include_router(router)
    return TestClient(app)


def test_generates_request_id_when_header_is_missing() -> None:
    client = build_test_client()

    response = client.get("/test/request-id")

    assert response.status_code == 200

    body = response.json()
    header_request_id = response.headers.get("x-request-id")

    assert header_request_id is not None
    assert header_request_id != ""
    assert body["request_id"] == header_request_id


def test_uses_incoming_x_request_id_when_valid() -> None:
    client = build_test_client()

    incoming_request_id = "proxy-req-12345"

    response = client.get(
        "/test/request-id",
        headers={"X-Request-ID": incoming_request_id},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == incoming_request_id
    assert response.json()["request_id"] == incoming_request_id


def test_ignores_invalid_incoming_x_request_id_and_generates_new_one() -> None:
    client = build_test_client()

    invalid_request_id = "bad value with spaces !!!"

    response = client.get(
        "/test/request-id",
        headers={"X-Request-ID": invalid_request_id},
    )

    assert response.status_code == 200

    body = response.json()
    header_request_id = response.headers.get("x-request-id")

    assert header_request_id is not None
    assert header_request_id != ""
    assert header_request_id != invalid_request_id
    assert body["request_id"] == header_request_id


def test_does_not_trust_incoming_request_id_when_disabled() -> None:
    app = FastAPI()
    app.add_middleware(
        RequestContextMiddleware,
        header_name="X-Request-ID",
        trust_incoming_request_id=False,
    )

    router = APIRouter()

    @router.get("/test/request-id-not-trusted")
    async def test_request_id_not_trusted() -> dict[str, str]:
        return {"request_id": get_request_id()}

    app.include_router(router)
    client = TestClient(app)

    response = client.get(
        "/test/request-id-not-trusted",
        headers={"X-Request-ID": "proxy-req-12345"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] != "proxy-req-12345"
    assert response.json()["request_id"] == response.headers["x-request-id"]

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.context import get_request_id
from app.main import create_app


def build_test_client() -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.get("/test/request-id-edge")
    async def request_id_edge() -> dict[str, str]:
        return {"request_id": get_request_id()}

    app.include_router(router)
    return TestClient(app)


def test_request_id_rejects_too_long_header() -> None:
    client = build_test_client()

    too_long_request_id = "a" * 129

    response = client.get(
        "/test/request-id-edge",
        headers={"X-Request-ID": too_long_request_id},
    )

    assert response.status_code == 200

    returned_request_id = response.json()["request_id"]
    header_request_id = response.headers["x-request-id"]

    assert returned_request_id == header_request_id
    assert returned_request_id != too_long_request_id
    assert returned_request_id != ""


def test_request_id_rejects_empty_header() -> None:
    client = build_test_client()

    response = client.get(
        "/test/request-id-edge",
        headers={"X-Request-ID": ""},
    )

    assert response.status_code == 200

    returned_request_id = response.json()["request_id"]
    header_request_id = response.headers["x-request-id"]

    assert returned_request_id == header_request_id
    assert returned_request_id != ""
    assert header_request_id != ""


def test_request_id_rejects_invalid_characters() -> None:
    client = build_test_client()

    invalid_request_id = "bad value !!!"

    response = client.get(
        "/test/request-id-edge",
        headers={"X-Request-ID": invalid_request_id},
    )

    assert response.status_code == 200

    returned_request_id = response.json()["request_id"]
    header_request_id = response.headers["x-request-id"]

    assert returned_request_id == header_request_id
    assert returned_request_id != invalid_request_id
    assert returned_request_id != ""


def test_request_id_preserves_valid_header() -> None:
    client = build_test_client()

    valid_request_id = "proxy-req-123_ABC:/x.y"

    response = client.get(
        "/test/request-id-edge",
        headers={"X-Request-ID": valid_request_id},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == valid_request_id
    assert response.json()["request_id"] == valid_request_id

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.errors import ConflictError, NotFoundError
from app.main import create_app


def build_test_client(*, raise_server_exceptions: bool = True) -> TestClient:
    app = create_app()
    router = APIRouter()

    @router.get("/test/not-found")
    async def test_not_found():
        raise NotFoundError(detail="User not found.")

    @router.get("/test/conflict")
    async def test_conflict():
        raise ConflictError(detail="Email already exists.")

    @router.get("/test/unhandled")
    async def test_unhandled():
        raise RuntimeError("boom")

    @router.get("/test/validation/{item_id}")
    async def test_validation(item_id: int):
        return {"item_id": item_id}

    app.include_router(router)
    return TestClient(app, raise_server_exceptions=raise_server_exceptions)


def test_not_found_problem_details() -> None:
    client = build_test_client()
    response = client.get("/test/not-found")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "problem:not-found"
    assert body["title"] == "Resource not found"
    assert body["status"] == 404
    assert body["detail"] == "User not found."
    assert body["error_code"] == "not_found"
    assert body["instance"] == "/test/not-found"
    assert "request_id" in body
    assert response.headers["x-request-id"] == body["request_id"]


def test_conflict_problem_details() -> None:
    client = build_test_client()
    response = client.get("/test/conflict")

    assert response.status_code == 409
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "problem:conflict"
    assert body["title"] == "Conflict"
    assert body["status"] == 409
    assert body["detail"] == "Email already exists."
    assert body["error_code"] == "conflict"
    assert body["instance"] == "/test/conflict"
    assert "request_id" in body
    assert response.headers["x-request-id"] == body["request_id"]


def test_validation_problem_details() -> None:
    client = build_test_client()
    response = client.get("/test/validation/not-an-int")

    assert response.status_code == 422
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "problem:validation-error"
    assert body["title"] == "Request validation failed"
    assert body["status"] == 422
    assert body["detail"] == "One or more request fields are invalid."
    assert body["error_code"] == "validation_error"
    assert body["instance"] == "/test/validation/not-an-int"
    assert "errors" in body
    assert len(body["errors"]) > 0
    assert "request_id" in body
    assert response.headers["x-request-id"] == body["request_id"]


def test_unhandled_problem_details() -> None:
    client = build_test_client(raise_server_exceptions=False)
    response = client.get("/test/unhandled")

    assert response.status_code == 500
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "problem:internal-error"
    assert body["title"] == "Internal Server Error"
    assert body["status"] == 500
    assert body["detail"] == "An unexpected error occurred."
    assert body["error_code"] == "internal_error"
    assert body["instance"] == "/test/unhandled"
    assert "request_id" in body
    assert response.headers["x-request-id"] == body["request_id"]


def test_route_not_found_problem_details() -> None:
    client = build_test_client()
    response = client.get("/missing-route")

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/problem+json")

    body = response.json()
    assert body["type"] == "problem:not-found"
    assert body["title"] == "Resource not found"
    assert body["status"] == 404
    assert body["detail"] == "The requested resource was not found."
    assert body["error_code"] == "not_found"
    assert body["instance"] == "/missing-route"
    assert "request_id" in body
    assert response.headers["x-request-id"] == body["request_id"]

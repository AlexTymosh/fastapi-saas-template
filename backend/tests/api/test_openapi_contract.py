from fastapi.testclient import TestClient

from app.core.config.settings import get_settings
from app.main import create_app


def _build_app(monkeypatch, *, docs_enabled: str):
    monkeypatch.setenv("API__DOCS_ENABLED", docs_enabled)
    get_settings.cache_clear()
    return create_app()


def test_openapi_json_exists_when_docs_enabled(monkeypatch) -> None:
    app = _build_app(monkeypatch, docs_enabled="true")
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 200
    spec = response.json()
    assert "paths" in spec
    assert "components" in spec


def test_openapi_json_absent_when_docs_disabled(monkeypatch) -> None:
    app = _build_app(monkeypatch, docs_enabled="false")
    client = TestClient(app)

    response = client.get("/openapi.json")

    assert response.status_code == 404


def test_openapi_contains_problem_details_schema(monkeypatch) -> None:
    app = _build_app(monkeypatch, docs_enabled="true")
    client = TestClient(app)

    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    schemas = spec["components"]["schemas"]

    assert "ProblemDetails" in schemas
    assert "InvalidParam" in schemas

    problem_details = schemas["ProblemDetails"]
    properties = problem_details["properties"]

    assert "type" in properties
    assert "title" in properties
    assert "status" in properties
    assert "detail" in properties
    assert "instance" in properties
    assert "error_code" in properties
    assert "request_id" in properties


def test_openapi_health_ready_documents_503_problem_response(monkeypatch) -> None:
    app = _build_app(monkeypatch, docs_enabled="true")
    client = TestClient(app)

    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    ready_get = spec["paths"]["/api/v1/health/ready"]["get"]
    responses = ready_get["responses"]

    assert "503" in responses

    content = responses["503"]["content"]
    assert "application/problem+json" in content

    schema_ref = content["application/problem+json"]["schema"]["$ref"]
    assert schema_ref.endswith("/ProblemDetails")

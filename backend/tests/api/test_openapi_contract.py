from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.settings import reset_settings_cache


def _build_app(monkeypatch, *, docs_enabled: str):
    monkeypatch.setenv("API__DOCS_ENABLED", docs_enabled)
    reset_settings_cache()
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

    health_live = spec["paths"]["/api/v1/health/live"]["get"]
    assert "429" not in health_live["responses"]
    assert "429" not in ready_get["responses"]


def test_openapi_includes_user_organisation_and_invite_endpoints(monkeypatch) -> None:
    app = _build_app(monkeypatch, docs_enabled="true")
    client = TestClient(app)

    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    paths = spec["paths"]

    assert "/api/v1/users/me" in paths
    assert "/api/v1/organisations" in paths
    assert "/api/v1/organisations/{organisation_id}" in paths
    assert "/api/v1/organisations/{organisation_id}/memberships" in paths
    assert "/api/v1/organisations/{organisation_id}/directory" in paths
    assert (
        "/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role"
        in paths
    )
    assert (
        "/api/v1/organisations/{organisation_id}/memberships/{membership_id}" in paths
    )
    assert "/api/v1/organisations/{organisation_id}/invites" in paths
    assert "/api/v1/invites/accept" in paths
    assert "/api/v1/organisations/{organisation_id}/invites/{invite_id}" in paths
    assert "/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend" in paths
    assert "/api/v1/invites/{token}/accept" not in paths

    invite_create = paths["/api/v1/organisations/{organisation_id}/invites"]["post"]
    invite_accept = paths["/api/v1/invites/accept"]["post"]
    invite_resend = paths[
        "/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend"
    ]["post"]

    create_problem = invite_create["responses"]["403"]["content"]
    assert "application/problem+json" in create_problem
    assert "429" in invite_create["responses"]
    assert "503" in invite_create["responses"]
    assert "application/problem+json" in invite_create["responses"]["429"]["content"]
    assert "application/problem+json" in invite_create["responses"]["503"]["content"]

    accept_problem = invite_accept["responses"]["404"]["content"]
    assert "application/problem+json" in accept_problem
    assert "429" in invite_accept["responses"]
    assert "503" in invite_accept["responses"]
    assert "application/problem+json" in invite_accept["responses"]["429"]["content"]
    assert "application/problem+json" in invite_accept["responses"]["503"]["content"]

    accept_request = invite_accept["requestBody"]["content"]["application/json"][
        "schema"
    ]
    assert accept_request["$ref"].endswith("/AcceptInviteRequest")

    assert "429" in invite_resend["responses"]
    assert "503" in invite_resend["responses"]
    assert "application/problem+json" in invite_resend["responses"]["429"]["content"]
    assert "application/problem+json" in invite_resend["responses"]["503"]["content"]


def test_openapi_membership_collection_response_has_data_meta_links(
    monkeypatch,
) -> None:
    app = _build_app(monkeypatch, docs_enabled="true")
    client = TestClient(app)

    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    memberships_path = "/api/v1/organisations/{organisation_id}/memberships"
    list_memberships = spec["paths"][memberships_path]["get"]
    schema_ref = list_memberships["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert schema_ref.endswith("/MembershipCollectionResponse")

    response_schema = spec["components"]["schemas"]["MembershipCollectionResponse"]
    assert set(response_schema["required"]) == {"data", "meta", "links"}
    properties = response_schema["properties"]
    assert "data" in properties
    assert "meta" in properties
    assert "links" in properties

    meta_schema_ref = properties["meta"]["$ref"]
    assert meta_schema_ref.endswith("/MembershipCollectionMeta")

    meta_schema = spec["components"]["schemas"]["MembershipCollectionMeta"]
    assert "total" in meta_schema["properties"]


def test_openapi_includes_platform_endpoints(monkeypatch) -> None:
    app = _build_app(monkeypatch, docs_enabled="true")
    client = TestClient(app)

    response = client.get("/openapi.json")
    assert response.status_code == 200

    spec = response.json()
    paths = spec["paths"]

    assert "/api/v1/platform/users" in paths
    assert "/api/v1/platform/users/{user_id}" in paths
    assert "/api/v1/platform/users/{user_id}/suspend" in paths
    assert "/api/v1/platform/users/{user_id}/restore" in paths
    assert "/api/v1/platform/organisations" in paths
    assert "/api/v1/platform/organisations/{organisation_id}" in paths
    assert "/api/v1/platform/organisations/{organisation_id}/suspend" in paths
    assert "/api/v1/platform/organisations/{organisation_id}/restore" in paths
    assert "/api/v1/platform/audit-events" in paths

    users_list = paths["/api/v1/platform/users"]["get"]
    users_schema_ref = users_list["responses"]["200"]["content"]["application/json"][
        "schema"
    ]["$ref"]
    assert users_schema_ref.endswith("/PlatformUsersCollectionResponse")
    assert "403" in users_list["responses"]
    assert "application/problem+json" in users_list["responses"]["403"]["content"]

    user_suspend = paths["/api/v1/platform/users/{user_id}/suspend"]["post"]
    assert "403" in user_suspend["responses"]
    assert "409" in user_suspend["responses"]
    assert "422" in user_suspend["responses"]
    assert "application/problem+json" in user_suspend["responses"]["409"]["content"]

    organisations_list = paths["/api/v1/platform/organisations"]["get"]
    org_schema_ref = organisations_list["responses"]["200"]["content"][
        "application/json"
    ]["schema"]["$ref"]
    assert org_schema_ref.endswith("/PlatformOrganisationsCollectionResponse")

    org_restore = paths["/api/v1/platform/organisations/{organisation_id}/restore"][
        "post"
    ]
    assert "403" in org_restore["responses"]
    assert "409" in org_restore["responses"]
    assert "422" in org_restore["responses"]

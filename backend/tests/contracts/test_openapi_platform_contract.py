from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.settings import reset_settings_cache

PLATFORM_PATHS = {
    "/api/v1/platform/me": {"get": "platform-identity"},
    "/api/v1/platform/users": {"get": "platform-users"},
    "/api/v1/platform/users/limited": {"get": "platform-users"},
    "/api/v1/platform/users/{user_id}": {"get": "platform-users"},
    "/api/v1/platform/users/{user_id}/suspend": {"post": "platform-users"},
    "/api/v1/platform/users/{user_id}/restore": {"post": "platform-users"},
    "/api/v1/platform/organisations": {"get": "platform-organisations"},
    "/api/v1/platform/organisations/limited": {"get": "platform-organisations"},
    "/api/v1/platform/organisations/{organisation_id}": {
        "get": "platform-organisations",
        "patch": "platform-organisations",
    },
    "/api/v1/platform/organisations/{organisation_id}/suspend": {
        "post": "platform-organisations"
    },
    "/api/v1/platform/organisations/{organisation_id}/restore": {
        "post": "platform-organisations"
    },
    "/api/v1/platform/audit-events": {"get": "platform-audit"},
    "/api/v1/platform/audit-events/limited": {"get": "platform-audit"},
    "/api/v1/platform/staff": {"get": "platform-staff", "post": "platform-staff"},
    "/api/v1/platform/staff/{staff_id}": {"get": "platform-staff"},
    "/api/v1/platform/staff/{staff_id}/role": {"patch": "platform-staff"},
    "/api/v1/platform/staff/{staff_id}/suspend": {"post": "platform-staff"},
    "/api/v1/platform/staff/{staff_id}/restore": {"post": "platform-staff"},
}

READ_POLICIES = {
    ("GET", "/api/v1/platform/me"): "platform_read",
    ("GET", "/api/v1/platform/users"): "platform_read",
    ("GET", "/api/v1/platform/users/limited"): "platform_read",
    ("GET", "/api/v1/platform/users/{user_id}"): "platform_read",
    ("GET", "/api/v1/platform/organisations"): "platform_read",
    ("GET", "/api/v1/platform/organisations/limited"): "platform_read",
    ("GET", "/api/v1/platform/organisations/{organisation_id}"): "platform_read",
    ("GET", "/api/v1/platform/audit-events"): "audit_read",
    ("GET", "/api/v1/platform/audit-events/limited"): "audit_read",
    ("GET", "/api/v1/platform/staff"): "platform_read",
    ("GET", "/api/v1/platform/staff/{staff_id}"): "platform_read",
}

WRITE_POLICIES = {
    ("POST", "/api/v1/platform/users/{user_id}/suspend"): "platform_write",
    ("POST", "/api/v1/platform/users/{user_id}/restore"): "platform_write",
    (
        "POST",
        "/api/v1/platform/organisations/{organisation_id}/suspend",
    ): "platform_write",
    (
        "POST",
        "/api/v1/platform/organisations/{organisation_id}/restore",
    ): "platform_write",
    ("PATCH", "/api/v1/platform/organisations/{organisation_id}"): "platform_write",
    ("POST", "/api/v1/platform/staff"): "platform_staff_write",
    ("PATCH", "/api/v1/platform/staff/{staff_id}/role"): "platform_staff_write",
    ("POST", "/api/v1/platform/staff/{staff_id}/suspend"): "platform_staff_write",
    ("POST", "/api/v1/platform/staff/{staff_id}/restore"): "platform_staff_write",
}


def _build_app(monkeypatch):
    monkeypatch.setenv("API__DOCS_ENABLED", "true")
    reset_settings_cache()
    return create_app()


def _openapi(monkeypatch):
    client = TestClient(_build_app(monkeypatch))
    response = client.get("/openapi.json")
    assert response.status_code == 200
    return response.json()


def _iter_dependant_calls(dependant):
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _iter_dependant_calls(dependency)


def _find_route(app, *, method: str, path: str) -> APIRoute:
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method in route.methods
        ):
            return route
    raise AssertionError(f"Route not found: {method} {path}")


def _route_has_policy(route: APIRoute, policy_name: str) -> bool:
    for call in _iter_dependant_calls(route.dependant):
        if getattr(call, "__rate_limit_policy_name__", None) == policy_name:
            return True
        if policy_name in getattr(call, "__rate_limit_policy_names__", ()):
            return True
    return False


def test_openapi_operation_ids_are_unique(monkeypatch) -> None:
    spec = _openapi(monkeypatch)
    operation_ids = [
        operation["operationId"]
        for path_item in spec["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "patch", "delete", "put"}
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_platform_operation_ids_are_frozen(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    expected_operation_ids = {
        ("get", "/api/v1/platform/me"): "get_platform_identity",
        ("get", "/api/v1/platform/users"): "list_platform_users",
        ("get", "/api/v1/platform/users/limited"): "list_limited_platform_users",
        ("get", "/api/v1/platform/users/{user_id}"): "get_platform_user",
        ("post", "/api/v1/platform/users/{user_id}/suspend"): "suspend_platform_user",
        ("post", "/api/v1/platform/users/{user_id}/restore"): "restore_platform_user",
        ("get", "/api/v1/platform/organisations"): "list_platform_organisations",
        (
            "get",
            "/api/v1/platform/organisations/limited",
        ): "list_limited_platform_organisations",
        (
            "get",
            "/api/v1/platform/organisations/{organisation_id}",
        ): "get_platform_organisation",
        (
            "patch",
            "/api/v1/platform/organisations/{organisation_id}",
        ): "patch_platform_organisation",
        (
            "post",
            "/api/v1/platform/organisations/{organisation_id}/suspend",
        ): "suspend_platform_organisation",
        (
            "post",
            "/api/v1/platform/organisations/{organisation_id}/restore",
        ): "restore_platform_organisation",
        ("get", "/api/v1/platform/audit-events"): "list_platform_audit_events",
        (
            "get",
            "/api/v1/platform/audit-events/limited",
        ): "list_limited_platform_audit_events",
        ("get", "/api/v1/platform/staff"): "list_platform_staff",
        ("post", "/api/v1/platform/staff"): "create_platform_staff",
        ("get", "/api/v1/platform/staff/{staff_id}"): "get_platform_staff",
        (
            "patch",
            "/api/v1/platform/staff/{staff_id}/role",
        ): "update_platform_staff_role",
        (
            "post",
            "/api/v1/platform/staff/{staff_id}/suspend",
        ): "suspend_platform_staff",
        (
            "post",
            "/api/v1/platform/staff/{staff_id}/restore",
        ): "restore_platform_staff",
    }

    for (method, path), operation_id in expected_operation_ids.items():
        assert spec["paths"][path][method]["operationId"] == operation_id


def test_platform_routes_are_documented_with_stable_operation_ids_and_tags(
    monkeypatch,
) -> None:
    spec = _openapi(monkeypatch)

    for path, methods in PLATFORM_PATHS.items():
        assert path in spec["paths"]
        for method, expected_tag in methods.items():
            operation = spec["paths"][path][method]
            assert operation["operationId"]
            assert "default" not in operation["operationId"].lower()
            assert expected_tag in operation["tags"]

    assert spec["paths"]["/api/v1/platform/me"]["get"]["tags"] == ["platform-identity"]


def test_health_endpoints_are_not_tagged_as_platform(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    for path in ("/api/v1/health/live", "/api/v1/health/ready"):
        for operation in spec["paths"][path].values():
            assert not any(tag.startswith("platform") for tag in operation["tags"])


def test_platform_routes_have_success_response_models(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    for path, methods in PLATFORM_PATHS.items():
        for method in methods:
            operation = spec["paths"][path][method]
            success_status = (
                "201" if (method, path) == ("post", "/api/v1/platform/staff") else "200"
            )
            success = operation["responses"][success_status]
            assert "application/json" in success["content"]
            schema = success["content"]["application/json"]["schema"]
            assert "$ref" in schema

    assert spec["paths"]["/api/v1/platform/users/limited"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]["$ref"].endswith(
        "/PlatformLimitedUsersCollectionResponse"
    )
    assert spec["paths"]["/api/v1/platform/organisations/limited"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]["$ref"].endswith(
        "/PlatformLimitedOrganisationsCollectionResponse"
    )


def test_platform_routes_declare_rate_limit_policies(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    for (method, path), policy_name in {**READ_POLICIES, **WRITE_POLICIES}.items():
        route = _find_route(app, method=method, path=path)
        assert _route_has_policy(route, policy_name), (method, path, policy_name)


def test_no_platform_route_is_undocumented_by_accident(monkeypatch) -> None:
    app = _build_app(monkeypatch)
    spec = _openapi(monkeypatch)
    documented = {
        (method.upper(), path)
        for path, methods in spec["paths"].items()
        if path.startswith("/api/v1/platform/")
        for method in methods
    }

    for route in app.routes:
        if isinstance(route, APIRoute) and route.path.startswith("/api/v1/platform/"):
            for method in route.methods or set():
                if method in {"HEAD", "OPTIONS"}:
                    continue
                assert (method, route.path) in documented

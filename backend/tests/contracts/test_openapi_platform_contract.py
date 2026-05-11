from __future__ import annotations

from collections.abc import Iterator

from fastapi.routing import APIRoute

from app.main import create_app

PLATFORM_TAGS = {
    "platform-identity",
    "platform-users",
    "platform-organisations",
    "platform-staff",
    "platform-audit",
}

PLATFORM_RESPONSE_MODEL_PATHS = [
    ("get", "/api/v1/platform/me"),
    ("get", "/api/v1/platform/users"),
    ("get", "/api/v1/platform/users/limited"),
    ("get", "/api/v1/platform/users/{user_id}"),
    ("post", "/api/v1/platform/users/{user_id}/suspend"),
    ("post", "/api/v1/platform/users/{user_id}/restore"),
    ("get", "/api/v1/platform/organisations"),
    ("get", "/api/v1/platform/organisations/limited"),
    ("get", "/api/v1/platform/organisations/{organisation_id}"),
    ("post", "/api/v1/platform/organisations/{organisation_id}/suspend"),
    ("post", "/api/v1/platform/organisations/{organisation_id}/restore"),
    ("patch", "/api/v1/platform/organisations/{organisation_id}"),
    ("get", "/api/v1/platform/audit-events"),
    ("get", "/api/v1/platform/audit-events/limited"),
    ("get", "/api/v1/platform/staff"),
    ("post", "/api/v1/platform/staff"),
    ("get", "/api/v1/platform/staff/{staff_id}"),
    ("patch", "/api/v1/platform/staff/{staff_id}/role"),
    ("post", "/api/v1/platform/staff/{staff_id}/suspend"),
    ("post", "/api/v1/platform/staff/{staff_id}/restore"),
]

EXPECTED_OPERATION_IDS = {
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
        "post",
        "/api/v1/platform/organisations/{organisation_id}/suspend",
    ): "suspend_platform_organisation",
    (
        "post",
        "/api/v1/platform/organisations/{organisation_id}/restore",
    ): "restore_platform_organisation",
    (
        "patch",
        "/api/v1/platform/organisations/{organisation_id}",
    ): "patch_platform_organisation",
    ("get", "/api/v1/platform/audit-events"): "list_platform_audit_events",
    (
        "get",
        "/api/v1/platform/audit-events/limited",
    ): "list_limited_platform_audit_events",
    ("get", "/api/v1/platform/staff"): "list_platform_staff",
    ("post", "/api/v1/platform/staff"): "create_platform_staff",
    ("get", "/api/v1/platform/staff/{staff_id}"): "get_platform_staff",
    ("patch", "/api/v1/platform/staff/{staff_id}/role"): "update_platform_staff_role",
    ("post", "/api/v1/platform/staff/{staff_id}/suspend"): "suspend_platform_staff",
    ("post", "/api/v1/platform/staff/{staff_id}/restore"): "restore_platform_staff",
}


def _iter_dependant_calls(dependant) -> Iterator[object]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _iter_dependant_calls(dependency)


def _route_policy_names(route: APIRoute) -> set[str]:
    names: set[str] = set()
    for call in _iter_dependant_calls(route.dependant):
        names.update(getattr(call, "__rate_limit_policy_names__", ()))
        name = getattr(call, "__rate_limit_policy_name__", None)
        if name is not None:
            names.add(name)
    return names


def _route_by_path_and_method(path: str, method: str) -> APIRoute:
    app = create_app()
    for route in app.routes:
        if (
            isinstance(route, APIRoute)
            and route.path == path
            and method.upper() in route.methods
        ):
            return route
    raise AssertionError(f"Route not found: {method.upper()} {path}")


def test_openapi_operation_ids_are_unique() -> None:
    spec = create_app().openapi()
    operation_ids = [
        operation["operationId"]
        for path_item in spec["paths"].values()
        for method, operation in path_item.items()
        if method in {"get", "post", "patch", "delete", "put"}
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_platform_routes_have_stable_operation_ids_and_tags() -> None:
    spec = create_app().openapi()

    for key, operation_id in EXPECTED_OPERATION_IDS.items():
        method, path = key
        operation = spec["paths"][path][method]
        assert operation["operationId"] == operation_id
        assert set(operation["tags"]).issubset(PLATFORM_TAGS)
        assert operation["tags"]

    assert spec["paths"]["/api/v1/platform/me"]["get"]["tags"] == ["platform-identity"]


def test_platform_routes_are_documented_and_have_response_models() -> None:
    spec = create_app().openapi()

    undocumented = [
        path
        for path in spec["paths"]
        if path.startswith("/api/v1/platform/") and not spec["paths"][path]
    ]
    assert undocumented == []

    for method, path in PLATFORM_RESPONSE_MODEL_PATHS:
        operation = spec["paths"][path][method]
        success_response = operation["responses"][
            "200"
            if method != "post" or path.endswith(("suspend", "restore"))
            else "201"
        ]
        schema = success_response["content"]["application/json"]["schema"]
        assert "$ref" in schema or schema.get("items") or schema.get("properties")


def test_platform_routes_have_expected_rate_limit_policy_metadata() -> None:
    read_paths = [
        ("GET", "/api/v1/platform/me", "platform_read"),
        ("GET", "/api/v1/platform/users", "platform_read"),
        ("GET", "/api/v1/platform/users/limited", "platform_read"),
        ("GET", "/api/v1/platform/users/{user_id}", "platform_read"),
        ("GET", "/api/v1/platform/organisations", "platform_read"),
        ("GET", "/api/v1/platform/organisations/limited", "platform_read"),
        ("GET", "/api/v1/platform/organisations/{organisation_id}", "platform_read"),
        ("GET", "/api/v1/platform/staff", "platform_read"),
        ("GET", "/api/v1/platform/staff/{staff_id}", "platform_read"),
        ("GET", "/api/v1/platform/audit-events", "audit_read"),
        ("GET", "/api/v1/platform/audit-events/limited", "audit_read"),
    ]
    write_paths = [
        ("POST", "/api/v1/platform/users/{user_id}/suspend", "platform_write"),
        ("POST", "/api/v1/platform/users/{user_id}/restore", "platform_write"),
        (
            "POST",
            "/api/v1/platform/organisations/{organisation_id}/suspend",
            "platform_write",
        ),
        (
            "POST",
            "/api/v1/platform/organisations/{organisation_id}/restore",
            "platform_write",
        ),
        ("PATCH", "/api/v1/platform/organisations/{organisation_id}", "platform_write"),
        ("POST", "/api/v1/platform/staff", "platform_staff_write"),
        ("PATCH", "/api/v1/platform/staff/{staff_id}/role", "platform_staff_write"),
        ("POST", "/api/v1/platform/staff/{staff_id}/suspend", "platform_staff_write"),
        ("POST", "/api/v1/platform/staff/{staff_id}/restore", "platform_staff_write"),
    ]

    for method, path, policy_name in [*read_paths, *write_paths]:
        route = _route_by_path_and_method(path, method)
        assert policy_name in _route_policy_names(route)


def test_health_endpoints_are_not_platform_tagged() -> None:
    spec = create_app().openapi()

    assert not set(
        spec["paths"]["/api/v1/health/live"]["get"].get("tags", [])
    ).intersection(PLATFORM_TAGS)
    assert not set(
        spec["paths"]["/api/v1/health/ready"]["get"].get("tags", [])
    ).intersection(PLATFORM_TAGS)

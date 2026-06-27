from __future__ import annotations

from types import UnionType
from typing import Any, get_args, get_origin

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.contract]
OPENAPI_METHODS = {"get", "post", "patch", "delete", "put"}
PLATFORM_TAGS = {
    "platform-identity",
    "platform-users",
    "platform-organisations",
    "platform-staff",
    "platform-audit",
    "platform-privacy",
}
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
    "/api/v1/platform/privacy/data-subject-requests": {"get": "platform-privacy"},
    "/api/v1/platform/privacy/data-subject-requests/{request_id}": {
        "get": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/review": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/approve": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/reject": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/cancel": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/fulfil": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/data-subject-requests/{request_id}/export-artifact": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/export-artifacts": {"get": "platform-privacy"},
    "/api/v1/platform/privacy/export-artifacts/{artifact_id}": {
        "get": "platform-privacy"
    },
    "/api/v1/platform/privacy/export-artifacts/{artifact_id}/download-url": {
        "post": "platform-privacy"
    },
    "/api/v1/platform/privacy/export-artifacts/{artifact_id}/confirm-delivery": {
        "post": "platform-privacy"
    },
}

EXPECTED_PLATFORM_OPERATION_IDS = {
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
    ("patch", "/api/v1/platform/staff/{staff_id}/role"): "update_platform_staff_role",
    ("post", "/api/v1/platform/staff/{staff_id}/suspend"): "suspend_platform_staff",
    ("post", "/api/v1/platform/staff/{staff_id}/restore"): "restore_platform_staff",
    (
        "get",
        "/api/v1/platform/privacy/data-subject-requests",
    ): "list_platform_data_subject_requests",
    (
        "get",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}",
    ): "get_platform_data_subject_request",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/review",
    ): "review_platform_data_subject_request",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/approve",
    ): "approve_platform_data_subject_request",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/reject",
    ): "reject_platform_data_subject_request",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/cancel",
    ): "cancel_platform_data_subject_request",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure",
    ): "execute_platform_data_subject_request_erasure",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/fulfil",
    ): "fulfil_platform_data_subject_request",
    (
        "post",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/export-artifact",
    ): "create_platform_export_artifact",
    (
        "get",
        "/api/v1/platform/privacy/export-artifacts",
    ): "list_platform_export_artifacts",
    (
        "get",
        "/api/v1/platform/privacy/export-artifacts/{artifact_id}",
    ): "get_platform_export_artifact",
    (
        "post",
        "/api/v1/platform/privacy/export-artifacts/{artifact_id}/download-url",
    ): "create_platform_export_download_url",
    (
        "post",
        "/api/v1/platform/privacy/export-artifacts/{artifact_id}/confirm-delivery",
    ): "confirm_platform_export_artifact_delivery",
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
    ("GET", "/api/v1/platform/privacy/data-subject-requests"): "platform_read",
    (
        "GET",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}",
    ): "platform_read",
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
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/review",
    ): "platform_write",
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/approve",
    ): "platform_write",
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/reject",
    ): "platform_write",
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/cancel",
    ): "platform_write",
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure",
    ): "platform_write",
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/fulfil",
    ): "platform_write",
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


def _schema_routes(app) -> list[APIRoute]:
    return [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.include_in_schema
    ]


def _expected_platform_contract_routes() -> set[tuple[str, str]]:
    return {
        (method.upper(), path)
        for path, methods in PLATFORM_PATHS.items()
        for method in methods
    }


def _actual_platform_schema_routes(app) -> set[tuple[str, str]]:
    routes: set[tuple[str, str]] = set()

    for route in _schema_routes(app):
        if not route.path.startswith("/api/v1/platform/"):
            continue
        for method in route.methods or set():
            if method in {"HEAD", "OPTIONS"}:
                continue
            routes.add((method, route.path))

    return routes


def _openapi_operations(spec):
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method in OPENAPI_METHODS:
                yield path, method, operation


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


def _resolve_ref_schema(spec, ref: str):
    schema_name = ref.split("/")[-1]
    return spec["components"]["schemas"][schema_name]


def _limited_collection_item_properties(spec, schema_name: str):
    collection_schema = spec["components"]["schemas"][schema_name]
    item_ref = collection_schema["properties"]["data"]["items"]["$ref"]
    return _resolve_ref_schema(spec, item_ref)["properties"]


def _is_pydantic_model(annotation: object) -> bool:
    return isinstance(annotation, type) and hasattr(annotation, "model_fields")


def _annotation_name(annotation: object) -> str:
    if hasattr(annotation, "__name__"):
        return annotation.__name__
    return repr(annotation)


def _assert_no_broad_response_annotations(
    annotation: object,
    *,
    path: str,
    field_path: str,
    seen: set[object] | None = None,
) -> None:
    """
    Recursively reject broad response annotations that degrade generated clients.

    Allowed:
    - Pydantic models
    - typed lists/sets/tuples
    - typed dicts with non-broad key/value types
    - Optional/Union wrappers around valid types

    Rejected:
    - Any
    - object
    - bare dict/list/set/tuple
    - dict/list/set/tuple without type arguments
    - nested Any/object inside containers

    Exception:
    - PlatformAuditEventResponse.metadata_json is intentionally broad because
      audit metadata is heterogeneous. Limited audit views must still hide it.
    """
    if seen is None:
        seen = set()

    allowed_broad_fields = {
        "PlatformAuditEventResponse.metadata_json",
    }

    if field_path in allowed_broad_fields:
        return

    if annotation in {Any, object}:
        raise AssertionError(
            f"{path}: {field_path} uses broad annotation {_annotation_name(annotation)}"
        )

    if annotation in {dict, list, set, tuple}:
        raise AssertionError(
            f"{path}: {field_path} uses bare container annotation "
            f"{_annotation_name(annotation)}"
        )

    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in {dict, list, set, tuple} and not args:
        raise AssertionError(
            f"{path}: {field_path} uses untyped container annotation "
            f"{_annotation_name(annotation)}"
        )

    if origin is dict:
        key_type, value_type = args
        _assert_no_broad_response_annotations(
            key_type,
            path=path,
            field_path=f"{field_path}.<key>",
            seen=seen,
        )
        _assert_no_broad_response_annotations(
            value_type,
            path=path,
            field_path=f"{field_path}.<value>",
            seen=seen,
        )
        return

    if origin in {list, set, tuple}:
        for index, item_type in enumerate(args):
            if item_type is Ellipsis:
                continue
            _assert_no_broad_response_annotations(
                item_type,
                path=path,
                field_path=f"{field_path}[{index}]",
                seen=seen,
            )
        return

    if origin in {UnionType, __import__("typing").Union}:
        for option in args:
            if option is type(None):
                continue
            _assert_no_broad_response_annotations(
                option,
                path=path,
                field_path=field_path,
                seen=seen,
            )
        return

    if args:
        for index, arg in enumerate(args):
            if arg is type(None):
                continue
            _assert_no_broad_response_annotations(
                arg,
                path=path,
                field_path=f"{field_path}[{index}]",
                seen=seen,
            )

    if not _is_pydantic_model(annotation):
        return

    if annotation in seen:
        return
    seen.add(annotation)

    for name, field in annotation.model_fields.items():
        _assert_no_broad_response_annotations(
            field.annotation,
            path=path,
            field_path=f"{annotation.__name__}.{name}",
            seen=seen,
        )


def test_all_schema_routes_have_non_empty_openapi_operation_ids(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    for path, method, operation in _openapi_operations(spec):
        assert operation.get("operationId"), (method, path)


def test_openapi_operation_ids_are_unique(monkeypatch) -> None:
    spec = _openapi(monkeypatch)
    operation_ids = [
        operation["operationId"] for _, _, operation in _openapi_operations(spec)
    ]

    assert len(operation_ids) == len(set(operation_ids))


def test_schema_route_names_are_unique(monkeypatch) -> None:
    app = _build_app(monkeypatch)
    route_names = [route.name for route in _schema_routes(app)]

    assert all(route_names)
    assert len(route_names) == len(set(route_names))


def test_openapi_operation_ids_match_route_names(monkeypatch) -> None:
    app = _build_app(monkeypatch)
    spec = app.openapi()

    for route in _schema_routes(app):
        for method in route.methods or set():
            method_lower = method.lower()
            if method_lower not in OPENAPI_METHODS:
                continue
            operation = spec["paths"][route.path][method_lower]
            assert operation["operationId"] == route.name


def test_platform_routes_are_documented_with_stable_operation_ids_and_tags(
    monkeypatch,
) -> None:
    spec = _openapi(monkeypatch)

    for path, methods in PLATFORM_PATHS.items():
        assert path in spec["paths"]
        for method, expected_tag in methods.items():
            operation = spec["paths"][path][method]
            assert (
                operation["operationId"]
                == EXPECTED_PLATFORM_OPERATION_IDS[(method, path)]
            )
            assert operation["tags"] == [expected_tag]
            assert set(operation["tags"]).issubset(PLATFORM_TAGS)
            assert "platform" not in operation["tags"]


def test_health_endpoints_are_not_tagged_as_platform(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    for path in ("/api/v1/health/live", "/api/v1/health/ready"):
        for operation in spec["paths"][path].values():
            assert not any(tag.startswith("platform") for tag in operation["tags"])


def test_platform_routes_have_required_typed_success_response_models(
    monkeypatch,
) -> None:
    app = _build_app(monkeypatch)
    spec = app.openapi()

    for route in _schema_routes(app):
        if not route.path.startswith("/api/v1/platform/"):
            continue
        if route.status_code == 204:
            continue
        assert route.response_model is not None, route.path
        origin = get_origin(route.response_model)
        assert route.response_model is not Any, route.path
        assert route.response_model not in {dict, list}, route.path
        assert origin not in {dict, list}, route.path

        for method in route.methods or set():
            method_lower = method.lower()
            if method_lower not in OPENAPI_METHODS:
                continue
            success_status = str(route.status_code or 200)
            success = spec["paths"][route.path][method_lower]["responses"][
                success_status
            ]
            assert "application/json" in success["content"]
            schema = success["content"]["application/json"]["schema"]
            assert "$ref" in schema, (method, route.path)

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


def test_platform_response_models_do_not_use_nested_broad_annotations(
    monkeypatch,
) -> None:
    app = _build_app(monkeypatch)

    for route in _schema_routes(app):
        if not route.path.startswith("/api/v1/platform/"):
            continue
        if route.status_code == 204:
            continue

        assert route.response_model is not None, route.path
        _assert_no_broad_response_annotations(
            route.response_model,
            path=route.path,
            field_path=route.response_model.__name__,
        )


def test_limited_platform_openapi_schemas_omit_restricted_fields(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    limited_audit = _limited_collection_item_properties(
        spec, "PlatformLimitedAuditEventsCollectionResponse"
    )
    assert not {
        "metadata_json",
        "ip_address",
        "user_agent",
        "reason",
        "actor_user_id",
    }.intersection(limited_audit)
    assert {"has_actor", "has_metadata", "has_reason"}.issubset(limited_audit)

    limited_users = _limited_collection_item_properties(
        spec, "PlatformLimitedUsersCollectionResponse"
    )
    assert not {
        "email",
        "email_verified",
        "suspended_at",
        "suspended_reason",
        "external_auth_id",
        "token",
        "access_token",
        "refresh_token",
        "platform_staff",
        "staff_id",
        "role",
        "permissions",
    }.intersection(limited_users)

    limited_organisations = _limited_collection_item_properties(
        spec, "PlatformLimitedOrganisationsCollectionResponse"
    )
    assert not {
        "suspended_at",
        "suspended_reason",
        "deleted_at",
        "deleted_by_user_id",
        "created_by_user_id",
        "updated_at",
        "owner_user_id",
        "membership_id",
    }.intersection(limited_organisations)


def test_platform_routes_declare_rate_limit_policies(monkeypatch) -> None:
    app = _build_app(monkeypatch)

    for (method, path), policy_name in {**READ_POLICIES, **WRITE_POLICIES}.items():
        route = _find_route(app, method=method, path=path)
        assert _route_has_policy(route, policy_name), (method, path, policy_name)


def test_platform_dsr_mutation_routes_use_function_scoped_write_context(
    monkeypatch,
) -> None:
    app = _build_app(monkeypatch)
    dsr_mutation_paths = {
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/review",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/approve",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/reject",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/cancel",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/fulfil",
    }
    for path in dsr_mutation_paths:
        route = _find_route(app, method="POST", path=path)
        assert any(
            getattr(dependency, "scope", None) == "function"
            and getattr(
                getattr(dependency, "call", None), "__rate_limit_policy_name__", None
            )
            == "platform_write"
            for dependency in route.dependant.dependencies
        ), path


def test_no_platform_route_is_undocumented_by_accident(monkeypatch) -> None:
    app = _build_app(monkeypatch)
    expected = _expected_platform_contract_routes()
    actual = _actual_platform_schema_routes(app)

    assert actual == expected, {
        "missing_from_contract": sorted(actual - expected),
        "stale_contract_entries": sorted(expected - actual),
    }


def test_platform_list_query_parameters_are_documented(monkeypatch) -> None:
    spec = _openapi(monkeypatch)

    limited_users_params = {
        parameter["name"]: parameter
        for parameter in spec["paths"]["/api/v1/platform/users/limited"]["get"][
            "parameters"
        ]
    }
    full_users_params = {
        parameter["name"]: parameter
        for parameter in spec["paths"]["/api/v1/platform/users"]["get"]["parameters"]
    }
    staff_params = {
        parameter["name"]: parameter
        for parameter in spec["paths"]["/api/v1/platform/staff"]["get"]["parameters"]
    }

    assert {"limit", "offset", "status", "q"}.issubset(limited_users_params)
    assert "exact_email" not in limited_users_params
    assert limited_users_params["limit"]["schema"]["maximum"] == 100
    assert limited_users_params["limit"]["schema"]["minimum"] == 1
    assert limited_users_params["offset"]["schema"]["minimum"] == 0
    q_string_schema = limited_users_params["q"]["schema"]["anyOf"][0]
    assert q_string_schema["maxLength"] == 255
    assert q_string_schema["minLength"] == 1

    assert {"limit", "offset", "status", "q"}.issubset(full_users_params)
    assert "exact_email" not in full_users_params
    assert {"limit", "offset", "status", "role"}.issubset(staff_params)
    assert staff_params["limit"]["schema"]["maximum"] == 100

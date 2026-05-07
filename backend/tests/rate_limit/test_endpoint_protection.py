from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.main import create_app

pytestmark = [pytest.mark.security, pytest.mark.rate_limit]


def find_route(app: FastAPI, *, path: str, method: str) -> APIRoute:
    expected_method = method.upper()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == path and expected_method in route.methods:
            return route
    raise AssertionError(f"Route not found: {expected_method} {path}")


def iter_dependant_calls(dependant) -> Iterator[object]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from iter_dependant_calls(dependency)


def route_rate_limit_policy_names(route: APIRoute) -> set[str]:
    return {
        policy_name
        for call in iter_dependant_calls(route.dependant)
        if (policy_name := getattr(call, "__rate_limit_policy_name__", None))
        is not None
    }


@pytest.mark.parametrize(
    ("method", "path", "policy_name"),
    [
        ("GET", "/api/v1/users/me", "authenticated_default"),
        ("POST", "/api/v1/organisations", "organisation_create"),
        ("GET", "/api/v1/organisations/{organisation_id}", "tenant_read"),
        (
            "GET",
            "/api/v1/organisations/{organisation_id}/directory",
            "tenant_read",
        ),
        (
            "GET",
            "/api/v1/organisations/{organisation_id}/memberships",
            "tenant_read",
        ),
        ("PATCH", "/api/v1/organisations/{organisation_id}", "tenant_write"),
        ("DELETE", "/api/v1/organisations/{organisation_id}", "tenant_write"),
        (
            "PATCH",
            "/api/v1/organisations/{organisation_id}/memberships/{membership_id}/role",
            "tenant_write",
        ),
        (
            "DELETE",
            "/api/v1/organisations/{organisation_id}/memberships/{membership_id}",
            "tenant_write",
        ),
        (
            "POST",
            "/api/v1/organisations/{organisation_id}/invites",
            "invite_create",
        ),
        ("POST", "/api/v1/invites/accept", "invite_accept"),
        (
            "DELETE",
            "/api/v1/organisations/{organisation_id}/invites/{invite_id}",
            "invite_mutation",
        ),
        (
            "POST",
            "/api/v1/organisations/{organisation_id}/invites/{invite_id}/resend",
            "invite_create",
        ),
        ("GET", "/api/v1/platform/users", "platform_read"),
        ("GET", "/api/v1/platform/users/{user_id}", "platform_read"),
        ("GET", "/api/v1/platform/organisations", "platform_read"),
        (
            "GET",
            "/api/v1/platform/organisations/{organisation_id}",
            "platform_read",
        ),
        ("GET", "/api/v1/platform/staff", "platform_read"),
        ("GET", "/api/v1/platform/audit-events/limited", "audit_read"),
        ("GET", "/api/v1/platform/audit-events", "audit_read"),
    ],
)
def test_sensitive_endpoint_has_expected_rate_limit_policy(
    method: str, path: str, policy_name: str
) -> None:
    app = create_app()
    route = find_route(app, path=path, method=method)

    assert policy_name in route_rate_limit_policy_names(route)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/health/live"),
        ("GET", "/api/v1/health/ready"),
    ],
)
def test_health_endpoints_have_no_app_level_rate_limit_policy(
    method: str, path: str
) -> None:
    app = create_app()
    route = find_route(app, path=path, method=method)

    assert route_rate_limit_policy_names(route) == set()

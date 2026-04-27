from __future__ import annotations

from collections.abc import Generator, Iterable

import pytest
from fastapi.routing import APIRoute

from app.main import create_app


def _find_route(app, path: str, method: str) -> APIRoute:
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        if route.path == path and method in route.methods:
            return route

    raise AssertionError(f"Route not found for {method} {path}")


def _iter_dependant_calls(dependant) -> Generator[object, None, None]:
    for dependency in dependant.dependencies:
        if dependency.call is not None:
            yield dependency.call
        yield from _iter_dependant_calls(dependency)


def _route_has_rate_limit_policy(route: APIRoute, policy_name: str) -> bool:
    calls: Iterable[object] = _iter_dependant_calls(route.dependant)
    return any(
        getattr(call, "__rate_limit_policy_name__", None) == policy_name
        for call in calls
    )


@pytest.mark.parametrize(
    ("method", "path", "policy_name"),
    [
        (
            "POST",
            "/api/v1/organisations/{organisation_id}/invites",
            "invite_create",
        ),
        ("POST", "/api/v1/invites/accept", "invite_accept"),
    ],
)
def test_sensitive_endpoint_has_expected_rate_limit_policy(
    method: str,
    path: str,
    policy_name: str,
) -> None:
    app = create_app()
    route = _find_route(app, path=path, method=method)

    assert route.path == path
    assert method in route.methods
    assert _route_has_rate_limit_policy(route, policy_name)

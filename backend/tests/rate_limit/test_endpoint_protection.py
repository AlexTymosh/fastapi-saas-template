from __future__ import annotations

from collections.abc import Iterator

from fastapi import FastAPI
from fastapi.routing import APIRoute

from app.main import create_app


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


def route_has_rate_limit_policy(route: APIRoute, policy_name: str) -> bool:
    return any(
        getattr(call, "__rate_limit_policy_name__", None) == policy_name
        for call in iter_dependant_calls(route.dependant)
    )


def test_invite_create_endpoint_has_invite_create_policy() -> None:
    app = create_app()
    route = find_route(
        app,
        path="/api/v1/organisations/{organisation_id}/invites",
        method="POST",
    )

    assert route.path == "/api/v1/organisations/{organisation_id}/invites"
    assert "POST" in route.methods
    assert route_has_rate_limit_policy(route, "invite_create")


def test_invite_accept_endpoint_has_invite_accept_policy() -> None:
    app = create_app()
    route = find_route(app, path="/api/v1/invites/accept", method="POST")

    assert route.path == "/api/v1/invites/accept"
    assert "POST" in route.methods
    assert route_has_rate_limit_policy(route, "invite_accept")

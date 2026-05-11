from __future__ import annotations

from fastapi.routing import APIRoute


def generate_route_name_operation_id(route: APIRoute) -> str:
    """Use globally unique route handler names as OpenAPI operation IDs."""
    if not route.name:
        raise ValueError(f"Route {route.path} must define a non-empty name")
    return route.name

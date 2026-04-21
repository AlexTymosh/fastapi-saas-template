from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from app.core.auth import (
    AuthenticatedPrincipal,
    CurrentPrincipal,
    extract_authenticated_principal,
)
from app.core.errors.handlers import register_exception_handlers


def _build_auth_boundary_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)

    router = APIRouter()

    @router.get("/protected")
    async def protected(principal: CurrentPrincipal) -> dict[str, Any]:
        return {
            "external_auth_id": principal.external_auth_id,
            "email": principal.email,
        }

    app.include_router(router)
    return app


def test_auth_boundary_returns_401_when_principal_is_missing() -> None:
    app = _build_auth_boundary_app()

    with TestClient(app) as client:
        response = client.get("/protected")

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_auth_boundary_returns_resolved_principal_from_override() -> None:
    app = _build_auth_boundary_app()

    async def _override() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id="kc-boundary-user",
            email="boundary@example.com",
            email_verified=True,
            first_name="Boundary",
            last_name="User",
        )

    app.dependency_overrides[extract_authenticated_principal] = _override

    with TestClient(app) as client:
        response = client.get("/protected")

    assert response.status_code == 200
    assert response.json()["external_auth_id"] == "kc-boundary-user"

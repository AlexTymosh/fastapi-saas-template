from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from fastapi.testclient import TestClient

from app.api.dependencies.domain_services import get_onboarding_service
from app.core.errors.exceptions import ConflictError
from app.main import create_app


@dataclass
class FakeOrganisation:
    id: object
    name: str
    slug: str


class FakeOnboardingService:
    def __init__(self) -> None:
        self.organisations: set[str] = set()

    async def create_organisation_for_current_user(
        self,
        *,
        identity,
        name: str,
        slug: str,
    ) -> FakeOrganisation:
        _ = identity
        if slug in self.organisations:
            raise ConflictError(detail="Organisation slug already exists.")

        self.organisations.add(slug)
        return FakeOrganisation(id=uuid4(), name=name, slug=slug)


def build_client() -> TestClient:
    app = create_app()
    fake_service = FakeOnboardingService()
    app.dependency_overrides[get_onboarding_service] = lambda: fake_service
    return TestClient(app)


def test_create_organisation_requires_authentication() -> None:
    client = build_client()

    response = client.post(
        "/api/v1/organisations",
        json={"name": "Acme", "slug": "acme"},
    )

    assert response.status_code == 401
    assert response.headers["content-type"].startswith("application/problem+json")


def test_create_organisation_slug_conflict_returns_problem_response() -> None:
    client = build_client()
    headers = {"X-Auth-Sub": "user-sub"}

    response_one = client.post(
        "/api/v1/organisations",
        json={"name": "Acme", "slug": "acme"},
        headers=headers,
    )
    response_two = client.post(
        "/api/v1/organisations",
        json={"name": "Acme 2", "slug": "acme"},
        headers=headers,
    )

    assert response_one.status_code == 200
    assert response_two.status_code == 409
    assert response_two.headers["content-type"].startswith("application/problem+json")

    body = response_two.json()
    assert body["type"] == "problem:conflict"
    assert body["status"] == 409
    assert body["detail"] == "Organisation slug already exists."
    assert body["instance"] == "/api/v1/organisations"

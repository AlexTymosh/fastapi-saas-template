from __future__ import annotations

import uuid

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient
from limits import RateLimitItemPerMinute

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.policies import RateLimitPolicy
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.rate_limit]


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_redis_rate_limiter_blocks_after_threshold(
    monkeypatch,
    redis_integration_url: str,
) -> None:
    test_suffix = uuid.uuid4().hex
    prefix = f"it-rl-{test_suffix}"

    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET", "test-rate-limit-identifier-secret-32chars"
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    reset_settings_cache()

    app = create_app()

    async def _principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id=f"integration-user-{test_suffix}",
            email="integration-user@example.com",
            email_verified=True,
        )

    app.dependency_overrides[get_authenticated_principal] = _principal

    router = APIRouter()
    policy = RateLimitPolicy(
        name=f"integration_probe_{test_suffix}",
        item=RateLimitItemPerMinute(5),
        fail_open=False,
    )

    @router.get(
        "/api/v1/integration/rate-limit",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            responses = [
                await client.get("/api/v1/integration/rate-limit") for _ in range(6)
            ]

    for response in responses[:5]:
        assert response.status_code == 200

    blocked_response = responses[5]
    assert blocked_response.status_code == 429
    assert blocked_response.headers["content-type"].startswith(
        "application/problem+json"
    )
    assert blocked_response.headers["retry-after"].isdigit()
    assert blocked_response.json()["error_code"] == "rate_limited"


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_redis_invite_create_organisation_bucket_is_shared_across_users(
    monkeypatch,
    redis_integration_url: str,
) -> None:
    test_suffix = uuid.uuid4().hex
    prefix = f"it-invite-rl-{test_suffix}"
    current_external_auth_id = "integration-user-a"

    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET", "test-rate-limit-identifier-secret-32chars"
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    monkeypatch.setenv(
        "RATE_LIMITING__POLICIES__INVITE_CREATE_ORGANISATION__LIMIT", "1"
    )
    reset_settings_cache()

    app = create_app()

    async def _principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id=current_external_auth_id,
            email=f"{current_external_auth_id}@example.com",
            email_verified=True,
        )

    app.dependency_overrides[get_authenticated_principal] = _principal

    from typing import Annotated
    from uuid import UUID

    from app.invites.api.rate_limits import (
        RateLimitedInviteCreateContext,
        require_rate_limited_invite_create_context,
    )

    router = APIRouter()

    @router.post("/api/v1/integration/layered-invites/{organisation_id}/create")
    async def _probe(
        organisation_id: UUID,
        context: Annotated[
            RateLimitedInviteCreateContext,
            Depends(require_rate_limited_invite_create_context),
        ],
    ) -> dict[str, str]:
        return {
            "organisation_id": str(organisation_id),
            "email": str(context.payload.email),
        }

    app.include_router(router)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first = await client.post(
                "/api/v1/integration/layered-invites/"
                "00000000-0000-4000-8000-000000000001/create",
                json={"email": "first@example.com", "role": "member"},
            )
            current_external_auth_id = "integration-user-b"
            second = await client.post(
                "/api/v1/integration/layered-invites/"
                "00000000-0000-4000-8000-000000000001/create",
                json={"email": "second@example.net", "role": "member"},
            )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.headers["content-type"].startswith("application/problem+json")
    assert second.json()["error_code"] == "rate_limited"
    assert "00000000-0000-4000-8000-000000000001" not in second.text
    assert "second@example.net" not in second.text

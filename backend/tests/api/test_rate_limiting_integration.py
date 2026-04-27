from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi import APIRouter, Depends
from httpx import ASGITransport, AsyncClient

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.policies import RateLimitPolicy
from app.main import create_app
from tests.helpers.settings import reset_settings_cache


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_redis_rate_limiter_blocks_after_threshold(
    monkeypatch,
    redis_integration_url: str,
) -> None:
    prefix = f"it-rl-{uuid.uuid4().hex}"

    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    reset_settings_cache()

    app = create_app()

    async def _principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id="integration-user",
            email="integration-user@example.com",
            email_verified=True,
            platform_roles=[],
        )

    app.dependency_overrides[get_authenticated_principal] = _principal

    router = APIRouter()
    policy = RateLimitPolicy(
        name="integration_probe",
        limit=5,
        window_seconds=60,
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
            tasks = [client.get("/api/v1/integration/rate-limit") for _ in range(10)]
            responses = await asyncio.gather(*tasks)

    status_codes = [response.status_code for response in responses]
    assert status_codes.count(200) == 5
    assert status_codes.count(429) == 5
    for response in responses:
        if response.status_code == 429:
            assert response.headers["content-type"].startswith(
                "application/problem+json"
            )
            assert response.headers["retry-after"].isdigit()
            assert response.json()["error_code"] == "rate_limited"

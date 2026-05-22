from __future__ import annotations

import uuid
from typing import Annotated

import pytest
from fastapi import APIRouter, Depends, Request
from httpx import ASGITransport, AsyncClient
from limits import RateLimitItemPerMinute

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.rate_limit.dependencies import (
    check_rate_limit,
    check_rate_limits_for_buckets,
    rate_limit_dependency,
)
from app.core.rate_limit.identifiers import RateLimitBucket
from app.core.rate_limit.policies import RateLimitPolicy
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.container]


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
async def test_real_redis_layered_invite_organisation_bucket_spans_two_users(
    monkeypatch,
    redis_integration_url: str,
) -> None:
    test_suffix = uuid.uuid4().hex
    prefix = f"it-invite-layered-{test_suffix}"
    organisation_id = f"00000000-0000-4000-8000-{test_suffix[:12]}"

    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET", "test-rate-limit-identifier-secret-32chars"
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    reset_settings_cache()

    app = create_app()
    current_external_auth_id = f"integration-user-a-{test_suffix}"

    async def _principal() -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal(
            external_auth_id=current_external_auth_id,
            email=f"{current_external_auth_id}@example.com",
            email_verified=True,
        )

    app.dependency_overrides[get_authenticated_principal] = _principal

    actor_policy = RateLimitPolicy(
        name=f"integration_invite_actor_{test_suffix}",
        item=RateLimitItemPerMinute(10),
        fail_open=False,
    )
    organisation_policy = RateLimitPolicy(
        name=f"integration_invite_organisation_{test_suffix}",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )
    router = APIRouter()

    @router.post("/api/v1/integration/invite-layered")
    async def _probe(
        request: Request,
        principal: Annotated[
            AuthenticatedPrincipal, Depends(get_authenticated_principal)
        ],
    ) -> dict[str, str]:
        await check_rate_limit(
            request=request,
            principal=principal,
            policy=actor_policy,
        )
        await check_rate_limits_for_buckets(
            request=request,
            checks=[
                (
                    organisation_policy,
                    RateLimitBucket(
                        kind="organisation",
                        raw_value=f"organisation:{organisation_id}",
                    ),
                )
            ],
        )
        return {"ok": "true"}

    app.include_router(router)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            first_response = await client.post("/api/v1/integration/invite-layered")
            current_external_auth_id = f"integration-user-b-{test_suffix}"
            second_response = await client.post("/api/v1/integration/invite-layered")

    assert first_response.status_code == 200
    assert second_response.status_code == 429
    assert second_response.headers["content-type"].startswith(
        "application/problem+json"
    )
    assert second_response.json()["error_code"] == "rate_limited"
    assert organisation_id not in second_response.text


@pytest.mark.integration
@pytest.mark.anyio
async def test_real_redis_grouped_rate_limit_is_atomic_under_concurrency(
    monkeypatch,
    redis_integration_url: str,
) -> None:
    test_suffix = uuid.uuid4().hex
    prefix = f"it-grouped-atomic-{test_suffix}"

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

    organisation_policy = RateLimitPolicy(
        name=f"integration_group_org_{test_suffix}",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )
    domain_policy = RateLimitPolicy(
        name=f"integration_group_domain_{test_suffix}",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    router = APIRouter()

    @router.post("/api/v1/integration/grouped-atomic")
    async def _probe(request: Request) -> dict[str, str]:
        await check_rate_limits_for_buckets(
            request=request,
            checks=[
                (
                    organisation_policy,
                    RateLimitBucket(kind="organisation", raw_value="organisation:1"),
                ),
                (
                    domain_policy,
                    RateLimitBucket(
                        kind="organisation_target_domain",
                        raw_value="organisation:1:domain:example.com",
                    ),
                ),
            ],
        )
        return {"ok": "true"}

    app.include_router(router)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            start = __import__("asyncio").Event()

            async def _fire() -> int:
                await start.wait()
                response = await client.post("/api/v1/integration/grouped-atomic")
                return response.status_code

            tasks = [__import__("asyncio").create_task(_fire()) for _ in range(30)]
            start.set()
            statuses = await __import__("asyncio").gather(*tasks)

    assert statuses.count(200) == 1
    assert statuses.count(429) == 29

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.platform.permissions import PlatformRole
from app.core.rate_limit.policies import (
    PLATFORM_STAFF_WRITE_POLICY,
    PLATFORM_WRITE_POLICY,
)
from app.main import create_app
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User
from app.users.services.users import UserService
from tests.helpers.auth import identity_for
from tests.helpers.settings import reset_settings_cache


def _assert_rate_limited_response(response) -> None:
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    exposed_headers = response.headers["access-control-expose-headers"]
    assert "Retry-After" in {header.strip() for header in exposed_headers.split(",")}


async def _seed_platform_admin(session_factory, *, test_suffix: str) -> User:
    async with session_factory() as session:
        async with session.begin():
            admin = await UserService(session).provision_current_user(
                identity_for(
                    f"kc-redis-platform-admin-{test_suffix}",
                    "redis-platform-admin@example.com",
                )
            )
            await PlatformStaffRepository(session).create_staff(
                user_id=admin.id,
                role=PlatformRole.PLATFORM_ADMIN.value,
            )
        return admin


async def _seed_users(
    session_factory,
    *,
    test_suffix: str,
    count: int,
    external_auth_id_prefix: str,
) -> list[User]:
    users: list[User] = []
    async with session_factory() as session:
        async with session.begin():
            service = UserService(session)
            for index in range(count):
                user = await service.provision_current_user(
                    identity_for(
                        f"{external_auth_id_prefix}-{test_suffix}-{index}",
                        f"redis-target-{index}@example.com",
                    )
                )
                users.append(user)
        return users


@asynccontextmanager
async def _build_redis_backed_client(
    *,
    monkeypatch: pytest.MonkeyPatch,
    redis_integration_url: str,
    migrated_database_url: str,
    identity: AuthenticatedPrincipal,
    prefix: str,
) -> AsyncIterator[AsyncClient]:
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    reset_settings_cache()

    app = create_app()

    async def _principal() -> AuthenticatedPrincipal:
        return identity

    app.dependency_overrides[get_authenticated_principal] = _principal

    async with app.router.lifespan_context(app):
        runtime = app.state.rate_limiter_runtime
        assert runtime.enabled is True
        assert runtime.storage is not None
        assert runtime.limiter is not None

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.mark.integration
@pytest.mark.anyio
async def test_platform_write_real_redis_blocks_after_policy_limit(
    monkeypatch,
    redis_integration_url: str,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    test_suffix = uuid.uuid4().hex
    admin = await _seed_platform_admin(
        migrated_session_factory,
        test_suffix=test_suffix,
    )
    targets = await _seed_users(
        migrated_session_factory,
        test_suffix=test_suffix,
        count=PLATFORM_WRITE_POLICY.item.amount + 1,
        external_auth_id_prefix="kc-redis-platform-target",
    )

    responses = []
    client_builder = _build_redis_backed_client(
        monkeypatch=monkeypatch,
        redis_integration_url=redis_integration_url,
        migrated_database_url=migrated_database_url,
        identity=identity_for(admin.external_auth_id, admin.email),
        prefix=f"it-platform-write-{test_suffix}",
    )
    async with client_builder as client:
        for target in targets:
            responses.append(
                await client.post(
                    f"/api/v1/platform/users/{target.id}/suspend",
                    json={"reason": "abuse investigation"},
                )
            )

    for response in responses[: PLATFORM_WRITE_POLICY.item.amount]:
        assert response.status_code == 200

    _assert_rate_limited_response(responses[PLATFORM_WRITE_POLICY.item.amount])


@pytest.mark.integration
@pytest.mark.anyio
async def test_platform_staff_write_real_redis_blocks_after_policy_limit(
    monkeypatch,
    redis_integration_url: str,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    test_suffix = uuid.uuid4().hex
    admin = await _seed_platform_admin(
        migrated_session_factory,
        test_suffix=test_suffix,
    )
    candidates = await _seed_users(
        migrated_session_factory,
        test_suffix=test_suffix,
        count=PLATFORM_STAFF_WRITE_POLICY.item.amount + 1,
        external_auth_id_prefix="kc-redis-staff-candidate",
    )

    responses = []
    client_builder = _build_redis_backed_client(
        monkeypatch=monkeypatch,
        redis_integration_url=redis_integration_url,
        migrated_database_url=migrated_database_url,
        identity=identity_for(admin.external_auth_id, admin.email),
        prefix=f"it-platform-staff-write-{test_suffix}",
    )
    async with client_builder as client:
        for candidate in candidates:
            responses.append(
                await client.post(
                    "/api/v1/platform/staff",
                    json={
                        "user_id": str(candidate.id),
                        "role": "support_agent",
                        "reason": "support coverage",
                    },
                )
            )

    for response in responses[: PLATFORM_STAFF_WRITE_POLICY.item.amount]:
        assert response.status_code == 200

    _assert_rate_limited_response(responses[PLATFORM_STAFF_WRITE_POLICY.item.amount])

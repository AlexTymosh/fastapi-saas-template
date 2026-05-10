from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.core.auth import get_authenticated_principal
from app.core.platform.permissions import PlatformRole
from app.main import create_app
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User, UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import FakeAuthProvider, identity_for
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.authz, pytest.mark.rate_limit]


def _seed_user(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                user.status = status
                await session.flush()
            return user

    return run_async(_run())


def _seed_platform_staff(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: str = PlatformRole.PLATFORM_ADMIN.value,
):
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role,
                )
            return user, staff

    return run_async(_run())


def _configure_real_redis_rate_limiter(
    monkeypatch,
    *,
    database_url: str,
    redis_url: str,
    prefix: str,
) -> None:
    monkeypatch.setenv("DATABASE__URL", database_url)
    monkeypatch.setenv("REDIS__URL", redis_url)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET", "test-rate-limit-identifier-secret-32chars"
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", prefix)
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    reset_settings_cache()


def _build_authenticated_app(*, external_auth_id: str, email: str):
    auth_provider = FakeAuthProvider(identity_for(external_auth_id, email))
    app = create_app()
    app.dependency_overrides[get_authenticated_principal] = (
        auth_provider.get_authenticated_principal
    )
    return app


def _assert_over_limit_response(response) -> None:
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert "Retry-After" in response.headers["access-control-expose-headers"]


@pytest.mark.integration
def test_platform_write_real_redis_blocks_after_policy_limit(
    monkeypatch,
    redis_integration_url: str,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    test_suffix = uuid.uuid4().hex
    prefix = f"it-platform-write-{test_suffix}"
    _configure_real_redis_rate_limiter(
        monkeypatch,
        database_url=migrated_database_url,
        redis_url=redis_integration_url,
        prefix=prefix,
    )
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id=f"kc-it-platform-admin-{test_suffix}",
        email=f"it-platform-admin-{test_suffix}@example.com",
    )
    targets = [
        _seed_user(
            migrated_session_factory,
            external_auth_id=f"kc-it-platform-target-{test_suffix}-{index}",
            email=f"it-platform-target-{test_suffix}-{index}@example.com",
        )
        for index in range(31)
    ]
    app = _build_authenticated_app(
        external_auth_id=admin.external_auth_id,
        email=admin.email,
    )

    with TestClient(app) as client:
        responses = [
            client.post(
                f"/api/v1/platform/users/{target.id}/suspend",
                json={"reason": "integration rate-limit probe"},
            )
            for target in targets
        ]

    for response in responses[:30]:
        assert response.status_code == 200

    _assert_over_limit_response(responses[30])


@pytest.mark.integration
def test_platform_staff_write_real_redis_blocks_after_policy_limit(
    monkeypatch,
    redis_integration_url: str,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    test_suffix = uuid.uuid4().hex
    prefix = f"it-platform-staff-write-{test_suffix}"
    _configure_real_redis_rate_limiter(
        monkeypatch,
        database_url=migrated_database_url,
        redis_url=redis_integration_url,
        prefix=prefix,
    )
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id=f"kc-it-staff-admin-{test_suffix}",
        email=f"it-staff-admin-{test_suffix}@example.com",
    )
    candidates = [
        _seed_user(
            migrated_session_factory,
            external_auth_id=f"kc-it-staff-candidate-{test_suffix}-{index}",
            email=f"it-staff-candidate-{test_suffix}-{index}@example.com",
        )
        for index in range(11)
    ]
    app = _build_authenticated_app(
        external_auth_id=admin.external_auth_id,
        email=admin.email,
    )

    with TestClient(app) as client:
        responses = [
            client.post(
                "/api/v1/platform/staff",
                json={
                    "user_id": str(candidate.id),
                    "role": "support_agent",
                    "reason": "integration staff rate-limit probe",
                },
            )
            for candidate in candidates
        ]

    for response in responses[:10]:
        assert response.status_code == 200

    _assert_over_limit_response(responses[10])

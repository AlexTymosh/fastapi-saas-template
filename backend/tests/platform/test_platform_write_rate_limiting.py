from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.platform.permissions import PlatformRole
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import (
    PLATFORM_STAFF_WRITE_POLICY,
    PLATFORM_WRITE_POLICY,
)
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User, UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.authz]


@dataclass
class _WindowStats:
    reset_time: float


class FakeLimiter:
    def __init__(self, *, allow: bool = True, raise_error: Exception | None = None):
        self.allow = allow
        self.raise_error = raise_error
        self.hit_calls: list[tuple[str, str, int, int]] = []
        self.window_calls: list[tuple[str, str, int, int]] = []

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        self.hit_calls.append((namespace, key, item.amount, item.multiples))
        return self.allow

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        self.window_calls.append((namespace, key, item.amount, item.multiples))
        return _WindowStats(reset_time=4_102_444_800.0)


def _install_fake_rate_limiter(monkeypatch, limiter: FakeLimiter) -> None:
    async def _fake_init_rate_limiter(app, settings) -> None:
        from app.core.rate_limit.registry import build_effective_policy_registry

        app.state.rate_limit_policy_registry = build_effective_policy_registry(settings)
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=True,
            storage=object(),
            limiter=limiter,
            strategy_name="moving-window",
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET", "test-rate-limit-identifier-secret-32chars"
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "platform-rl-test")
    reset_settings_cache()


def _attach_fake_rate_limiter(client, limiter: FakeLimiter) -> None:
    from app.core.config.settings import get_settings
    from app.core.rate_limit.registry import build_effective_policy_registry

    client.app.state.rate_limit_policy_registry = build_effective_policy_registry(
        get_settings()
    )
    client.app.state.rate_limiter_runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=limiter,
        strategy_name="moving-window",
    )


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


def _seed_organisation(session_factory, *, name: str, slug: str) -> Organisation:
    async def _run():
        async with session_factory() as session:
            async with session.begin():
                org = Organisation(name=name, slug=slug)
                session.add(org)
            return org

    return run_async(_run())


def test_platform_user_suspend_over_limit_returns_429_and_does_not_suspend_user(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(allow=False)
    _install_fake_rate_limiter(monkeypatch, limiter)
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-rl-platform-admin",
        email="rl-platform-admin@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-rl-target-user",
        email="rl-target-user@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(bundle.client, limiter)

    response = bundle.client.post(
        f"/api/v1/platform/users/{target.id}/suspend",
        json={"reason": "security_incident"},
    )

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert response.headers["access-control-expose-headers"] == "Retry-After"
    assert limiter.hit_calls[0][0].startswith("platform-rl-test:platform_write:")
    assert limiter.hit_calls[0][1].startswith("rlid:v1:hmac-sha256:")
    assert admin.external_auth_id not in limiter.hit_calls[0][1]
    assert limiter.hit_calls[0][2] == PLATFORM_WRITE_POLICY.default_limit

    async def _verify() -> None:
        async with migrated_session_factory() as session:
            updated = await session.get(User, target.id)
            assert updated is not None
            assert updated.status == UserStatus.ACTIVE

    run_async(_verify())


def test_platform_organisation_suspend_over_limit_returns_429_and_does_not_mutate(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(allow=False)
    _install_fake_rate_limiter(monkeypatch, limiter)
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-rl-org-admin",
        email="rl-org-admin@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Rate Ltd", slug="rate")
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(bundle.client, limiter)

    response = bundle.client.post(
        f"/api/v1/platform/organisations/{org.id}/suspend",
        json={"reason": "compliance_review"},
    )

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert limiter.hit_calls[0][0].startswith("platform-rl-test:platform_write:")

    async def _verify() -> None:
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.status == OrganisationStatus.ACTIVE

    run_async(_verify())


def test_platform_staff_write_uses_stricter_policy(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(allow=False)
    _install_fake_rate_limiter(monkeypatch, limiter)
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-rl-staff-admin",
        email="rl-staff-admin@example.com",
    )
    candidate = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-rl-staff-candidate",
        email="rl-staff-candidate@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(bundle.client, limiter)

    response = bundle.client.post(
        "/api/v1/platform/staff",
        json={
            "user_id": str(candidate.id),
            "role": "support_agent",
            "reason": "support coverage",
        },
    )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert limiter.hit_calls[0][0].startswith("platform-rl-test:platform_staff_write:")
    assert limiter.hit_calls[0][2] == PLATFORM_STAFF_WRITE_POLICY.default_limit

    async def _verify() -> None:
        async with migrated_session_factory() as session:
            staff = await PlatformStaffRepository(session).get_by_user_id(candidate.id)
            assert staff is None

    run_async(_verify())


def test_platform_write_unauthenticated_request_returns_401_before_rate_limit(
    client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(allow=False)
    _install_fake_rate_limiter(monkeypatch, limiter)
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-rl-unauth-target",
        email="rl-unauth-target@example.com",
    )
    client = client_factory(
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(client, limiter)

    response = client.post(
        f"/api/v1/platform/users/{target.id}/suspend",
        json={"reason": "security_incident"},
    )

    assert response.status_code == 401
    assert limiter.hit_calls == []


def test_platform_write_forbidden_principal_remains_403_when_limit_allows(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(allow=True)
    _install_fake_rate_limiter(monkeypatch, limiter)
    support, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-rl-support",
        email="rl-support@example.com",
        role=PlatformRole.SUPPORT_AGENT.value,
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-rl-forbidden-target",
        email="rl-forbidden-target@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(support.external_auth_id, support.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(bundle.client, limiter)

    response = bundle.client.post(
        f"/api/v1/platform/users/{target.id}/suspend",
        json={"reason": "security_incident"},
    )

    assert response.status_code == 403
    assert limiter.hit_calls[0][0].startswith("platform-rl-test:platform_write:")


def test_platform_write_rate_limiter_failure_is_fail_closed(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(raise_error=RuntimeError("redis down"))
    _install_fake_rate_limiter(monkeypatch, limiter)
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-rl-fail-admin",
        email="rl-fail-admin@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-rl-fail-target",
        email="rl-fail-target@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(bundle.client, limiter)

    response = bundle.client.post(
        f"/api/v1/platform/users/{target.id}/suspend",
        json={"reason": "security_incident"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_platform_write_over_limit_does_not_enter_transaction_or_service_body(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    limiter = FakeLimiter(allow=False)
    _install_fake_rate_limiter(monkeypatch, limiter)
    admin, _ = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-rl-boundary-admin",
        email="rl-boundary-admin@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-rl-boundary-target",
        email="rl-boundary-target@example.com",
    )
    bundle = authenticated_client_factory(
        identity=identity_for(admin.external_auth_id, admin.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )
    _attach_fake_rate_limiter(bundle.client, limiter)

    begin_calls = 0
    actor_resolution_calls = 0
    service_calls = 0

    from sqlalchemy.ext.asyncio import AsyncSession

    from app.platform.services.platform_users import PlatformUsersService

    original_begin = AsyncSession.begin

    def _spy_begin(self):
        nonlocal begin_calls
        begin_calls += 1
        return original_begin(self)

    async def _spy_resolve_platform_actor(**kwargs):
        nonlocal actor_resolution_calls
        actor_resolution_calls += 1
        raise AssertionError("over-limit request must not resolve platform actor")

    async def _spy_suspend_user(self, **kwargs):
        nonlocal service_calls
        service_calls += 1
        raise AssertionError("over-limit request must not call platform write service")

    monkeypatch.setattr(AsyncSession, "begin", _spy_begin)
    monkeypatch.setattr(
        "app.core.platform.write_context.resolve_platform_actor",
        _spy_resolve_platform_actor,
    )
    monkeypatch.setattr(PlatformUsersService, "suspend_user", _spy_suspend_user)

    response = bundle.client.post(
        f"/api/v1/platform/users/{target.id}/suspend",
        json={"reason": "security_incident"},
    )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert begin_calls == 0
    assert actor_resolution_calls == 0
    assert service_calls == 0

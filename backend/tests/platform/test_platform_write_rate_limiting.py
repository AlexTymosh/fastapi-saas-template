from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace

from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.organisations.models.organisation import Organisation
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User, UserStatus
from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for
from tests.helpers.settings import reset_settings_cache


@dataclass(frozen=True)
class _WindowStats:
    reset_time: float


class _ThresholdLimiter:
    def __init__(self, *, threshold: int, raise_error: Exception | None = None) -> None:
        self.threshold = threshold
        self.raise_error = raise_error
        self.hit_calls: list[tuple[str, str, int, int]] = []
        self.window_calls: list[tuple[str, str, int, int]] = []

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        self.hit_calls.append((namespace, key, item.amount, item.multiples))
        return len(self.hit_calls) <= self.threshold

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        self.window_calls.append((namespace, key, item.amount, item.multiples))
        return _WindowStats(reset_time=time.time() + 42)


def _install_fake_rate_limiter(monkeypatch, limiter: _ThresholdLimiter) -> None:
    async def _fake_init_rate_limiter(app, settings) -> None:
        app.state.rate_limiter_runtime = RateLimiterRuntime(
            enabled=True,
            storage=object(),
            limiter=limiter,
            strategy_name="test",
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-platform-rl")
    monkeypatch.setenv("RATE_LIMITING__TRUST_PROXY_HEADERS", "false")
    reset_settings_cache()


def _seed_user(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    status: UserStatus = UserStatus.ACTIVE,
) -> User:
    async def _run() -> User:
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                user.status = status
            return user

    return run_async(_run())


def _seed_platform_staff(
    session_factory,
    *,
    external_auth_id: str,
    email: str,
    role: PlatformStaffRole = PlatformStaffRole.PLATFORM_ADMIN,
    status: PlatformStaffStatus = PlatformStaffStatus.ACTIVE,
) -> SimpleNamespace:
    async def _run() -> SimpleNamespace:
        async with session_factory() as session:
            async with session.begin():
                user = await UserService(session).provision_current_user(
                    identity_for(external_auth_id, email)
                )
                staff = await PlatformStaffRepository(session).create_staff(
                    user_id=user.id,
                    role=role.value,
                )
                staff.status = status.value
                await session.flush()
            return SimpleNamespace(user=user, staff=staff)

    return run_async(_run())


def _seed_organisation(session_factory, *, name: str, slug: str) -> Organisation:
    async def _run() -> Organisation:
        async with session_factory() as session:
            async with session.begin():
                org = Organisation(name=name, slug=slug)
                session.add(org)
            return org

    return run_async(_run())


def _assert_rate_limited(response) -> None:
    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert response.headers["access-control-expose-headers"] == "Retry-After"


def test_platform_user_suspend_is_rate_limited_after_policy_exhaustion(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-admin-user",
        email="platform-rl-admin-user@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-target-user",
        email="platform-rl-target-user@example.com",
    )
    limiter = _ThresholdLimiter(threshold=30)
    _install_fake_rate_limiter(monkeypatch, limiter)

    bundle = authenticated_client_factory(
        identity=identity_for(admin.user.external_auth_id, admin.user.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )

    with bundle.client as client:
        responses = [
            client.post(
                f"/api/v1/platform/users/{target.id}/suspend",
                json={"reason": "security review"},
            )
            for _ in range(31)
        ]

    assert responses[0].status_code == 200
    _assert_rate_limited(responses[-1])
    assert limiter.hit_calls[-1][0].startswith("test-platform-rl:platform_write:")
    assert limiter.hit_calls[-1][2] == 30


def test_platform_organisation_patch_is_rate_limited_and_final_write_is_not_executed(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-admin-org",
        email="platform-rl-admin-org@example.com",
    )
    org = _seed_organisation(migrated_session_factory, name="Original", slug="orig")
    limiter = _ThresholdLimiter(threshold=30)
    _install_fake_rate_limiter(monkeypatch, limiter)

    bundle = authenticated_client_factory(
        identity=identity_for(admin.user.external_auth_id, admin.user.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )

    with bundle.client as client:
        responses = [
            client.patch(
                f"/api/v1/platform/organisations/{org.id}",
                json={
                    "name": f"Allowed {idx}",
                    "slug": f"allowed-{idx}",
                    "reason": "profile correction",
                },
            )
            for idx in range(30)
        ]
        blocked = client.patch(
            f"/api/v1/platform/organisations/{org.id}",
            json={
                "name": "Blocked Name",
                "slug": "blocked-name",
                "reason": "should not execute",
            },
        )

    assert all(response.status_code == 200 for response in responses)
    _assert_rate_limited(blocked)

    async def _verify() -> None:
        async with migrated_session_factory() as session:
            updated = await session.get(Organisation, org.id)
            assert updated is not None
            assert updated.name == "Allowed 29"
            assert updated.slug == "allowed-29"

    run_async(_verify())


def test_platform_staff_write_uses_stricter_staff_policy(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-admin-staff",
        email="platform-rl-admin-staff@example.com",
    )
    candidate = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-candidate-staff",
        email="platform-rl-candidate-staff@example.com",
    )
    limiter = _ThresholdLimiter(threshold=0)
    _install_fake_rate_limiter(monkeypatch, limiter)

    bundle = authenticated_client_factory(
        identity=identity_for(admin.user.external_auth_id, admin.user.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )

    with bundle.client as client:
        response = client.post(
            "/api/v1/platform/staff",
            json={
                "user_id": str(candidate.id),
                "role": "support_agent",
                "reason": "new support",
            },
        )

    _assert_rate_limited(response)
    assert limiter.hit_calls == [
        (
            limiter.hit_calls[0][0],
            limiter.hit_calls[0][1],
            10,
            1,
        )
    ]
    assert limiter.hit_calls[0][0].startswith("test-platform-rl:platform_staff_write:")


def test_platform_write_rate_limiter_is_fail_closed(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-admin-failclosed",
        email="platform-rl-admin-failclosed@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-target-failclosed",
        email="platform-rl-target-failclosed@example.com",
    )
    limiter = _ThresholdLimiter(threshold=0, raise_error=RuntimeError("redis down"))
    _install_fake_rate_limiter(monkeypatch, limiter)

    bundle = authenticated_client_factory(
        identity=identity_for(admin.user.external_auth_id, admin.user.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )

    with bundle.client as client:
        response = client.post(
            f"/api/v1/platform/users/{target.id}/restore",
            json={"reason": "restore"},
        )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_unauthenticated_platform_write_returns_401_before_limiter(
    client_factory,
    migrated_database_url,
    monkeypatch,
) -> None:
    limiter = _ThresholdLimiter(threshold=0)
    _install_fake_rate_limiter(monkeypatch, limiter)

    with client_factory(
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    ) as client:
        response = client.post(
            "/api/v1/platform/users/00000000-0000-0000-0000-000000000001/suspend",
            json={"reason": "missing auth"},
        )

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"
    assert limiter.hit_calls == []


def test_authenticated_non_platform_user_gets_403_when_not_over_limit(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    regular = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-regular",
        email="platform-rl-regular@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-regular-target",
        email="platform-rl-regular-target@example.com",
    )
    limiter = _ThresholdLimiter(threshold=30)
    _install_fake_rate_limiter(monkeypatch, limiter)

    bundle = authenticated_client_factory(
        identity=identity_for(regular.external_auth_id, regular.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )

    with bundle.client as client:
        response = client.post(
            f"/api/v1/platform/users/{target.id}/suspend",
            json={"reason": "not allowed"},
        )

    assert response.status_code == 403
    assert response.json()["error_code"] == "forbidden"
    assert len(limiter.hit_calls) == 1


def test_over_limit_platform_write_does_not_change_target_state(
    authenticated_client_factory,
    migrated_database_url,
    migrated_session_factory,
    monkeypatch,
) -> None:
    admin = _seed_platform_staff(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-admin-noop",
        email="platform-rl-admin-noop@example.com",
    )
    target = _seed_user(
        migrated_session_factory,
        external_auth_id="kc-platform-rl-target-noop",
        email="platform-rl-target-noop@example.com",
    )
    limiter = _ThresholdLimiter(threshold=0)
    _install_fake_rate_limiter(monkeypatch, limiter)

    bundle = authenticated_client_factory(
        identity=identity_for(admin.user.external_auth_id, admin.user.email),
        database_url=migrated_database_url,
        rate_limiting_enabled=True,
    )

    with bundle.client as client:
        response = client.post(
            f"/api/v1/platform/users/{target.id}/suspend",
            json={"reason": "should not execute"},
        )

    _assert_rate_limited(response)

    async def _verify() -> None:
        async with migrated_session_factory() as session:
            updated = await session.get(User, target.id)
            assert updated is not None
            assert updated.status == UserStatus.ACTIVE

    run_async(_verify())

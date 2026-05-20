from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, get_authenticated_principal
from app.core.db.session import get_db_session
from app.core.rate_limit.business import (
    check_authorized_tenant_write_business_rate_limit,
)
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import TENANT_WRITE_ORGANISATION_POLICY
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security]


@dataclass
class _WindowStats:
    reset_time: float


class FakeLimiter:
    def __init__(
        self,
        *,
        allow: bool = True,
        allow_sequence: list[bool] | None = None,
        raise_error: Exception | None = None,
    ):
        self.allow = allow
        self.allow_sequence = list(allow_sequence or [])
        self.raise_error = raise_error
        self.hit_calls: list[tuple[str, str, int, int]] = []
        self.window_calls: list[tuple[str, str, int, int]] = []

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        self.hit_calls.append((namespace, key, item.amount, item.multiples))
        if self.allow_sequence:
            return self.allow_sequence.pop(0)
        return self.allow

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        self.window_calls.append((namespace, key, item.amount, item.multiples))
        return _WindowStats(reset_time=4_102_444_800.0)


async def _principal_user_a() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
    )


def _build_app(monkeypatch, *, limiter: FakeLimiter) -> TestClient:
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
    monkeypatch.setenv("RATE_LIMITING__PRE_AUTH_ENABLED", "false")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET",
        "test-rate-limit-identifier-secret-32chars",
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    reset_settings_cache()
    return TestClient(create_app())


def test_tenant_write_organisation_policy_is_distinct_and_declarative() -> None:
    assert TENANT_WRITE_ORGANISATION_POLICY.name == "tenant_write_organisation"
    assert TENANT_WRITE_ORGANISATION_POLICY.default_limit == 60
    assert TENANT_WRITE_ORGANISATION_POLICY.default_window_seconds == 60
    assert TENANT_WRITE_ORGANISATION_POLICY.default_fail_open is False
    assert TENANT_WRITE_ORGANISATION_POLICY.sensitivity == "sensitive"


@pytest.mark.anyio
async def test_tenant_write_organisation_bucket_is_shared_per_organisation_and_private(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=True)
    client = _build_app(monkeypatch, limiter=fake)
    request = SimpleNamespace(
        app=client.app,
        client=SimpleNamespace(host="127.0.0.1"),
        headers={},
    )
    organisation_a = uuid4()
    organisation_b = uuid4()

    with client:
        await check_authorized_tenant_write_business_rate_limit(
            request=request,
            organisation_id=organisation_a,
        )
        await check_authorized_tenant_write_business_rate_limit(
            request=request,
            organisation_id=organisation_a,
        )
        await check_authorized_tenant_write_business_rate_limit(
            request=request,
            organisation_id=organisation_b,
        )

    keys = [call[1] for call in fake.hit_calls]
    assert keys[0] == keys[1]
    assert keys[2] != keys[0]

    for namespace, key, *_ in fake.hit_calls:
        assert namespace.startswith("test-rl:tenant_write_organisation:organisation")
        assert str(organisation_a) not in namespace
        assert str(organisation_a) not in key
        assert str(organisation_b) not in namespace
        assert str(organisation_b) not in key


def test_tenant_write_organisation_bucket_blocks_after_actor_limit_before_mutation(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow_sequence=[True, False])
    client = _build_app(monkeypatch, limiter=fake)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    actor_user_id = uuid4()
    mutation_started = {"value": False}

    async def _db_override():
        yield AsyncMock(spec=AsyncSession)

    class FakeUserService:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def provision_current_user(
            self,
            identity: AuthenticatedPrincipal,
        ) -> SimpleNamespace:
            assert identity.external_auth_id == "user-a"
            return SimpleNamespace(id=actor_user_id)

    class FakeOrganisationService:
        def __init__(self, session: AsyncSession) -> None:
            self.session = session

        async def update_organisation_details(
            self,
            *,
            organisation_id: UUID,
            actor_user_id: UUID,
            audit_context,
            name: str | None = None,
            slug: str | None = None,
            business_rate_limiter=None,
        ):
            assert business_rate_limiter is not None
            await business_rate_limiter()
            mutation_started["value"] = True
            raise AssertionError(
                "tenant write mutation must not run after organisation bucket denial"
            )

    client.app.dependency_overrides[get_db_session] = _db_override
    monkeypatch.setattr(
        "app.organisations.api.organisations.UserService",
        FakeUserService,
    )
    monkeypatch.setattr(
        "app.organisations.api.organisations.OrganisationService",
        FakeOrganisationService,
    )

    with client as api_client:
        response = api_client.patch(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001",
            json={"name": "Blocked Ltd"},
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert mutation_started["value"] is False
    assert len(fake.hit_calls) == 2
    assert fake.hit_calls[0][0].startswith("test-rl:tenant_write:user")
    assert fake.hit_calls[1][0].startswith(
        "test-rl:tenant_write_organisation:organisation"
    )

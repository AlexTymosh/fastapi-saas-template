from __future__ import annotations

import asyncio
import time
from hashlib import sha256
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from fastapi import Depends
from limits import RateLimitItemPerMinute
from sqlalchemy import select

from app.core.auth import AuthenticatedPrincipal
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.policies import RateLimitPolicy
from app.invites.services.delivery import get_invite_token_sink
from app.main import create_app
from app.memberships.models.membership import Membership, MembershipRole
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async


class InMemoryInviteTokenSink:
    def __init__(self) -> None:
        self._tokens_by_email: dict[str, str] = {}

    async def deliver(self, *, invite, raw_token: str) -> None:
        self._tokens_by_email[invite.email.lower()] = raw_token

    def token_for_email(self, email: str) -> str:
        return self._tokens_by_email[email.lower()]


def _identity_for(
    external_auth_id: str,
    email: str,
    roles: list[str] | None = None,
) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
        email=email,
        email_verified=True,
        platform_roles=roles or [],
    )


def _override_token_sink(test_client) -> InMemoryInviteTokenSink:
    sink = InMemoryInviteTokenSink()
    test_client.app.dependency_overrides[get_invite_token_sink] = lambda: sink
    return sink


def test_invite_accept_transfers_membership(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner", "owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(owner_client)

    source_owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-source-owner", "source-owner@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    source_owner_client = source_owner_client_bundle.client
    source_owner_sink = _override_token_sink(source_owner_client)

    with source_owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Source", "slug": "org-source"},
        )
        assert create_org.status_code == 201
        source_org_id = create_org.json()["id"]

        seed_invite = client.post(
            f"/api/v1/organisations/{source_org_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert seed_invite.status_code == 201

    with owner_client as client:
        create_target_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org A", "slug": "orga"},
        )
        assert create_target_org.status_code == 201
        target_org_id = create_target_org.json()["id"]

        transfer_invite = client.post(
            f"/api/v1/organisations/{target_org_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )
        assert transfer_invite.status_code == 201

    source_token = source_owner_sink.token_for_email("invitee@example.com")
    transfer_token = owner_sink.token_for_email("invitee@example.com")

    invitee_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee", "invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_client = invitee_client_bundle.client

    with invitee_client as client:
        accepted_source = client.post(
            "/api/v1/invites/accept",
            json={"token": source_token},
        )
        assert accepted_source.status_code == 200

        accepted = client.post(
            "/api/v1/invites/accept",
            json={"token": transfer_token},
        )
        assert accepted.status_code == 200

        me = client.get("/api/v1/users/me")
        assert me.status_code == 200
        assert me.json()["membership"]["organisation_id"] == target_org_id

    async def _assert_membership_transfer() -> None:
        async with migrated_session_factory() as session:
            user_result = await session.execute(
                select(User).where(User.external_auth_id == "kc-invitee")
            )
            invitee = user_result.scalar_one()

            memberships_result = await session.execute(
                select(Membership).where(Membership.user_id == invitee.id)
            )
            memberships = list(memberships_result.scalars().all())
            assert len(memberships) == 2

            source_membership = next(
                membership
                for membership in memberships
                if str(membership.organisation_id) == source_org_id
            )
            target_membership = next(
                membership
                for membership in memberships
                if str(membership.organisation_id) == target_org_id
            )

            assert source_membership.is_active is False
            assert target_membership.is_active is True
            assert target_membership.role == MembershipRole.MEMBER

    run_async(_assert_membership_transfer())


def test_invite_accept_rejects_transfer_for_sole_owner(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-sole", "owner-sole@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(owner_client)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Sole Target", "slug": "org-sole-target"},
        )
        assert create_org.status_code == 201
        target_org_id = create_org.json()["id"]

        invite_response = client.post(
            f"/api/v1/organisations/{target_org_id}/invites",
            json={"email": "invitee-sole@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201

    sole_owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-sole", "invitee-sole@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    sole_owner_client = sole_owner_client_bundle.client
    with sole_owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Sole Source", "slug": "org-sole-source"},
        )
        assert create_org.status_code == 201

    token = owner_sink.token_for_email("invitee-sole@example.com")
    with sole_owner_client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
        assert response.status_code == 409


def test_superadmin_can_invite_without_membership(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-2", "owner2@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org C", "slug": "orgc"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]

    super_client_bundle = authenticated_client_factory(
        identity=_identity_for(
            "kc-super",
            "super@example.com",
            roles=["superadmin"],
        ),
        database_url=migrated_database_url,
        redis_url=None,
    )
    super_client = super_client_bundle.client
    _override_token_sink(super_client)
    with super_client as client:
        response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "new@example.com", "role": "admin"},
        )

    assert response.status_code == 201


def test_old_invite_accept_path_route_is_not_available(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-legacy-path", "legacy@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    client = client_bundle.client
    with client as api_client:
        response = api_client.post("/api/v1/invites/some-token/accept")

    assert response.status_code == 404


def test_invite_accepts_for_first_login_user_without_projection(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-jit", "owner-jit@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(owner_client)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org JIT", "slug": "org-jit"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "jit-invitee@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        assert "token" not in invite_response.json()

    token = owner_sink.token_for_email("jit-invitee@example.com")

    invitee_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-jit", "jit-invitee@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_client = invitee_client_bundle.client
    with invitee_client as client:
        accepted = client.post("/api/v1/invites/accept", json={"token": token})
        assert accepted.status_code == 200

    async def _assert_user_and_membership() -> None:
        async with migrated_session_factory() as session:
            user_result = await session.execute(
                select(User).where(User.external_auth_id == "kc-invitee-jit")
            )
            user = user_result.scalar_one()
            assert user.email == "jit-invitee@example.com"

            membership_result = await session.execute(
                select(Membership).where(Membership.user_id == user.id)
            )
            membership = membership_result.scalar_one()
            assert membership.organisation_id == UUID(org_id)

    run_async(_assert_user_and_membership())


def test_accept_invite_rejects_email_mismatch(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-mismatch", "owner-mismatch@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(owner_client)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Mismatch", "slug": "org-mismatch"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "expected@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201
        assert "token" not in invite_response.json()

    token = owner_sink.token_for_email("expected@example.com")

    wrong_user_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-wrong-email", "wrong@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    wrong_user_client = wrong_user_client_bundle.client
    with wrong_user_client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
    assert response.status_code == 403


def test_accept_invite_rejects_expired_invite(
    authenticated_client_factory,
    migrated_database_url: str,
    migrated_session_factory,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-expired", "owner-expired@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(owner_client)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Expired", "slug": "org-expired"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]

        invite_response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "invitee-expired@example.com", "role": "member"},
        )
        assert invite_response.status_code == 201

    token = owner_sink.token_for_email("invitee-expired@example.com")

    async def _expire_invite() -> None:
        from datetime import UTC, datetime, timedelta

        from app.invites.models.invite import Invite, InviteStatus

        token_hash = sha256(token.encode("utf-8")).hexdigest()
        async with migrated_session_factory() as session:
            result = await session.execute(
                select(Invite).where(
                    Invite.token_hash == token_hash,
                    Invite.status == InviteStatus.PENDING,
                )
            )
            invite = result.scalars().first()
            assert invite is not None
            invite.expires_at = datetime.now(UTC) - timedelta(minutes=1)
            await session.commit()

    run_async(_expire_invite())

    invitee_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-invitee-expired", "invitee-expired@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    invitee_client = invitee_client_bundle.client
    with invitee_client as client:
        response = client.post("/api/v1/invites/accept", json={"token": token})
        assert response.status_code == 409


def test_create_invite_rejects_owner_role(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-role", "owner-role@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    _override_token_sink(owner_client)
    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Org Role", "slug": "org-role"},
        )
        assert create_org.status_code == 201
        org_id = create_org.json()["id"]
        response = client.post(
            f"/api/v1/organisations/{org_id}/invites",
            json={"email": "invitee-owner@example.com", "role": "owner"},
        )
    assert response.status_code == 422


def test_create_invite_returns_single_resource_contract(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-contract", "owner-contract@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    _override_token_sink(owner_client)
    invite_email = "contract-invitee@example.com"
    invite_role = "member"

    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Invite Contract Org", "slug": "invite-contract-org"},
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": invite_email, "role": invite_role},
        )

    assert response.status_code == 201
    body = response.json()
    assert "invite" not in body
    assert "id" in body
    assert "email" in body
    assert "organisation_id" in body
    assert "role" in body
    assert "status" in body
    assert "expires_at" in body
    assert "created_at" in body
    assert "updated_at" in body
    assert body["email"] == invite_email
    assert body["organisation_id"] == organisation_id
    assert body["role"] == invite_role
    assert body["status"] == "pending"


def test_create_invite_returns_404_for_missing_organisation(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-missing-org", "owner-missing-org@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    _override_token_sink(owner_client)
    with owner_client as client:
        response = client.post(
            "/api/v1/organisations/00000000-0000-0000-0000-000000000001/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 404


def test_create_invite_returns_403_when_organisation_exists_but_actor_has_no_access(
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    owner_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-owner-no-access", "owner-no-access@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    owner_client = owner_client_bundle.client
    owner_sink = _override_token_sink(owner_client)

    with owner_client as client:
        create_org = client.post(
            "/api/v1/organisations",
            json={"name": "Invite Access Org", "slug": "invite-access-org"},
        )
        assert create_org.status_code == 201
        organisation_id = create_org.json()["id"]

    outsider_client_bundle = authenticated_client_factory(
        identity=_identity_for("kc-outsider-invite", "outsider-invite@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )
    outsider_client = outsider_client_bundle.client
    _override_token_sink(outsider_client)

    with outsider_client as client:
        response = client.post(
            f"/api/v1/organisations/{organisation_id}/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 403
    assert owner_sink._tokens_by_email == {}


class _WindowStats:
    def __init__(self, reset_time: float) -> None:
        self.reset_time = reset_time


class _FakeLimiter:
    def __init__(self, *, blocked_after: dict[str, int] | None = None) -> None:
        self._blocked_after = blocked_after or {}
        self._hits: dict[str, int] = {}

    async def hit(self, item, key: str) -> bool:
        count = self._hits.get(key, 0) + 1
        self._hits[key] = count
        threshold = self._blocked_after.get(key, self._blocked_after.get("*", 1000000))
        return count <= threshold

    async def get_window_stats(self, item, key: str):
        return _WindowStats(reset_time=time.time() + 120)


class _FailingLimiter:
    async def hit(self, item, key: str) -> bool:
        raise TimeoutError("backend timeout")

    async def get_window_stats(self, item, key: str):
        return _WindowStats(reset_time=time.time() + 60)


def _patch_rate_limiter_runtime(monkeypatch, runtime) -> None:
    async def _setup(app, settings) -> None:
        app.state.rate_limit_runtime = runtime

    async def _teardown(app) -> None:
        app.state.rate_limit_runtime = None

    monkeypatch.setattr("app.main.setup_rate_limiter", _setup)
    monkeypatch.setattr("app.main.teardown_rate_limiter", _teardown)


def test_invite_accept_rate_limited_returns_429_problem_details(
    monkeypatch,
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("REDIS__URL", "redis://placeholder:6379/0")

    limiter = _FakeLimiter(blocked_after={"*": 0})
    _patch_rate_limiter_runtime(
        monkeypatch,
        SimpleNamespace(limiter=limiter, storage=None, strategy_name="moving-window"),
    )

    bundle = authenticated_client_factory(
        identity=_identity_for("kc-ratelimit", "ratelimit@example.com"),
        database_url=migrated_database_url,
        redis_url="redis://placeholder:6379/0",
    )

    with bundle.client as client:
        response = client.post("/api/v1/invites/accept", json={"token": "x"})

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert response.headers["access-control-expose-headers"] == "Retry-After"


def test_invite_sensitive_policy_returns_503_when_limiter_unavailable(
    monkeypatch,
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("REDIS__URL", "redis://placeholder:6379/0")

    runtime = SimpleNamespace(
        limiter=_FailingLimiter(),
        storage=None,
        strategy_name="moving-window",
    )
    _patch_rate_limiter_runtime(monkeypatch, runtime)

    bundle = authenticated_client_factory(
        identity=_identity_for("kc-ratelimit-2", "ratelimit2@example.com"),
        database_url=migrated_database_url,
        redis_url="redis://placeholder:6379/0",
    )

    with bundle.client as client:
        response = client.post("/api/v1/invites/accept", json={"token": "x"})

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_rate_limiter_fail_open_allows_request_and_logs_warning(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")

    policy = RateLimitPolicy(
        name="test_fail_open",
        limit=RateLimitItemPerMinute(1),
        fail_open=True,
    )
    dependency = rate_limit_dependency(policy)

    app = create_app()
    app.state.rate_limit_runtime = SimpleNamespace(
        limiter=_FailingLimiter(),
        storage=None,
        strategy_name="moving-window",
    )

    @app.get("/test/fail-open", dependencies=[Depends(dependency)])
    async def _route():
        return {"ok": True}

    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        response = client.get("/test/fail-open")

    assert response.status_code == 200
    assert any(
        "rate_limiter_unavailable_fail_open" in rec.message for rec in caplog.records
    )


@pytest.mark.integration
def test_invite_accept_rate_limit_with_real_redis_concurrency(
    monkeypatch,
    redis_integration_url: str,
    migrated_database_url: str,
) -> None:
    from app.core.auth import get_authenticated_principal
    from app.core.auth_claims import AuthenticatedPrincipal
    from app.core.rate_limit.policies import INVITE_ACCEPT_POLICY

    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("REDIS__URL", redis_integration_url)
    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "rl-int-test")

    app = create_app()

    async def _principal_override():
        return AuthenticatedPrincipal(
            external_auth_id="kc-concurrent",
            email="concurrent@example.com",
            email_verified=True,
            platform_roles=[],
        )

    app.dependency_overrides[get_authenticated_principal] = _principal_override

    async def _scenario() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
        ) as client:
            requests = [
                client.post("/api/v1/invites/accept", json={"token": "missing-token"})
                for _ in range(INVITE_ACCEPT_POLICY.limit.amount + 2)
            ]
            responses = await asyncio.gather(*requests)

        status_codes = [item.status_code for item in responses]
        assert status_codes.count(429) >= 2

    from tests.helpers.asyncio_runner import run_async

    try:
        run_async(_scenario())
    finally:
        from app.core.redis import close_redis

        run_async(close_redis())


def test_rate_limiting_disabled_does_not_require_runtime(
    monkeypatch,
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "false")

    bundle = authenticated_client_factory(
        identity=_identity_for("kc-no-limit", "nolimit@example.com"),
        database_url=migrated_database_url,
        redis_url=None,
    )

    with bundle.client as client:
        response = client.post("/api/v1/invites/accept", json={"token": "x"})

    assert response.status_code != 503


def test_invite_endpoints_use_separate_rate_limit_namespaces(
    monkeypatch,
    authenticated_client_factory,
    migrated_database_url: str,
) -> None:
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true")
    monkeypatch.setenv("REDIS__URL", "redis://placeholder:6379/0")

    limiter = _FakeLimiter(blocked_after={"*": 100})
    _patch_rate_limiter_runtime(
        monkeypatch,
        SimpleNamespace(limiter=limiter, storage=None, strategy_name="moving-window"),
    )

    bundle = authenticated_client_factory(
        identity=_identity_for("kc-key-scope", "scope@example.com"),
        database_url=migrated_database_url,
        redis_url="redis://placeholder:6379/0",
    )

    with bundle.client as client:
        client.post("/api/v1/invites/accept", json={"token": "x"})
        client.post(
            "/api/v1/organisations/00000000-0000-0000-0000-000000000001/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    keys = list(limiter._hits.keys())
    assert any(":invite_accept:" in key for key in keys)
    assert any(":invite_create:" in key for key in keys)

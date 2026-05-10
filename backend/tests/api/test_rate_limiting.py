from __future__ import annotations

import inspect
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Annotated
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from limits import RateLimitItemPerMinute
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import (
    AuthenticatedPrincipal,
    get_authenticated_principal,
    require_authenticated_principal,
)
from app.core.db.session import get_db_session
from app.core.observability import rate_limit_metrics
from app.core.rate_limit.dependencies import rate_limit_dependency
from app.core.rate_limit.lifecycle import RateLimiterRuntime
from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    TENANT_WRITE_POLICY,
    RateLimitPolicy,
)
from app.invites.api.rate_limits import (
    RateLimitedInviteCreateContext,
    RateLimitedInviteMutationContext,
    require_rate_limited_invite_create_context,
    require_rate_limited_invite_resend_context,
)
from app.main import create_app
from tests.helpers.settings import reset_settings_cache

pytestmark = [pytest.mark.security, pytest.mark.rate_limit]


@dataclass
class _WindowStats:
    reset_time: float


class StatefulLimiter:
    def __init__(self) -> None:
        self.hit_calls: list[tuple[str, str, int, int]] = []
        self.hit_expiries: list[int] = []
        self.window_calls: list[tuple[str, str, int, int]] = []
        self._counts: dict[tuple[str, str], int] = {}

    async def hit(self, item, namespace: str, key: str) -> bool:
        self.hit_calls.append((namespace, key, item.amount, item.multiples))
        self.hit_expiries.append(item.get_expiry())
        counter_key = (namespace, key)
        count = self._counts.get(counter_key, 0) + 1
        self._counts[counter_key] = count
        return count <= item.amount

    async def get_window_stats(self, item, namespace: str, key: str) -> _WindowStats:
        self.window_calls.append((namespace, key, item.amount, item.multiples))
        return _WindowStats(reset_time=4_102_444_800.0)


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
        self.hit_expiries: list[int] = []
        self.window_calls: list[tuple[str, str, int, int]] = []

    async def hit(self, item, namespace: str, key: str) -> bool:
        if self.raise_error is not None:
            raise self.raise_error
        self.hit_calls.append((namespace, key, item.amount, item.multiples))
        self.hit_expiries.append(item.get_expiry())
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


async def _principal_user_b() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-b",
        email="user-b@example.com",
        email_verified=True,
    )


def _build_app(
    monkeypatch,
    *,
    enabled: bool,
    runtime: RateLimiterRuntime | None = None,
    policy_limits: dict[str, int] | None = None,
) -> TestClient:
    async def _fake_init_rate_limiter(app, settings) -> None:
        from app.core.rate_limit.registry import build_effective_policy_registry

        app.state.rate_limit_policy_registry = build_effective_policy_registry(settings)
        app.state.rate_limiter_runtime = runtime or RateLimiterRuntime(
            enabled=False,
            storage=None,
            limiter=None,
            strategy_name=None,
        )

    monkeypatch.setattr("app.main.init_rate_limiter", _fake_init_rate_limiter)
    monkeypatch.setenv("RATE_LIMITING__ENABLED", "true" if enabled else "false")
    monkeypatch.setenv(
        "RATE_LIMITING__IDENTIFIER_SECRET",
        "test-rate-limit-identifier-secret-32chars",
    )
    monkeypatch.setenv("RATE_LIMITING__REDIS_PREFIX", "test-rl")
    for policy_name, limit in (policy_limits or {}).items():
        env_name = f"RATE_LIMITING__POLICIES__{policy_name.upper()}__LIMIT"
        monkeypatch.setenv(env_name, str(limit))
    reset_settings_cache()

    app = create_app()
    probe_policy = RateLimitPolicy(
        name="test_probe",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )
    fail_open_policy = RateLimitPolicy(
        name="test_fail_open",
        item=RateLimitItemPerMinute(1),
        fail_open=True,
    )

    router = APIRouter()

    @router.get(
        "/api/v1/test/rate-limit/protected",
        dependencies=[Depends(rate_limit_dependency(probe_policy))],
    )
    async def _protected_probe() -> dict[str, str]:
        return {"ok": "true"}

    @router.get(
        "/api/v1/test/rate-limit/fail-open",
        dependencies=[Depends(rate_limit_dependency(fail_open_policy))],
    )
    async def _fail_open_probe() -> dict[str, str]:
        return {"ok": "true"}

    app.include_router(router)
    return TestClient(app)


def _install_invite_endpoint_over_limit_guards(client: TestClient, monkeypatch):
    db_session_opened = False

    async def _db_session_should_not_open():
        nonlocal db_session_opened
        db_session_opened = True
        raise AssertionError("invite endpoint opened DB session before rate limiting")
        yield  # pragma: no cover

    invite_service_cls = MagicMock()
    user_service_cls = MagicMock()
    client.app.dependency_overrides[get_db_session] = _db_session_should_not_open
    monkeypatch.setattr("app.invites.api.invites.InviteService", invite_service_cls)
    monkeypatch.setattr("app.invites.api.invites.UserService", user_service_cls)

    return invite_service_cls, user_service_cls, lambda: db_session_opened


def test_default_test_configuration_does_not_start_rate_limiter(monkeypatch) -> None:
    with _build_app(monkeypatch, enabled=False) as client:
        runtime = client.app.state.rate_limiter_runtime

    assert runtime.enabled is False
    assert runtime.storage is None
    assert runtime.limiter is None


def test_rate_limiting_disabled_is_noop(monkeypatch) -> None:
    with _build_app(monkeypatch, enabled=False) as client:
        response = client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 401


def test_over_limit_returns_429_problem_with_retry_after(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 429
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limited"
    assert response.headers["retry-after"].isdigit()
    assert response.headers["access-control-expose-headers"] == "Retry-After"


def test_rate_limiter_failure_fail_closed_returns_503(monkeypatch) -> None:
    fake = FakeLimiter(raise_error=RuntimeError("redis down"))
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_missing_identifier_secret_returns_503_without_hitting_limiter(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=True)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    settings_without_identifier_secret = SimpleNamespace(
        rate_limiting=SimpleNamespace(
            enabled=True,
            trust_proxy_headers=False,
            identifier_secret=None,
            redis_prefix="test-rl",
            storage_timeout_seconds=1.0,
        )
    )

    with patch(
        "app.core.rate_limit.dependencies.get_settings",
        return_value=settings_without_identifier_secret,
    ):
        with client as api_client:
            response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"
    assert fake.hit_calls == []


def test_rate_limiter_failure_fail_open_allows_request(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(raise_error=RuntimeError("redis down")),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/fail-open")

    assert response.status_code == 200


@pytest.mark.parametrize("runtime_mode", ["missing_runtime", "none_limiter"])
def test_runtime_unavailable_records_observability_and_returns_503(
    monkeypatch, runtime_mode: str
) -> None:
    endpoint_body_called = False
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=True),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    app = client.app
    app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    policy = RateLimitPolicy(
        name="test_runtime_unavailable",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )
    router = APIRouter()

    @router.get(
        "/api/v1/test/rate-limit/runtime-unavailable",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe() -> dict[str, str]:
        nonlocal endpoint_body_called
        endpoint_body_called = True
        return {"ok": "true"}

    app.include_router(router)

    with (
        patch(
            "app.core.rate_limit.dependencies.record_rate_limit_backend_error",
        ) as backend_error,
        patch(
            "app.core.rate_limit.dependencies.record_rate_limit_decision"
        ) as decision,
        patch(
            "app.core.rate_limit.dependencies.record_rate_limit_check_duration"
        ) as duration,
    ):
        with client as api_client:
            if runtime_mode == "missing_runtime":
                delattr(api_client.app.state, "rate_limiter_runtime")
            else:
                api_client.app.state.rate_limiter_runtime = RateLimiterRuntime(
                    enabled=True,
                    storage=object(),
                    limiter=None,
                    strategy_name="moving-window",
                )

            response = api_client.get("/api/v1/test/rate-limit/runtime-unavailable")

    assert response.status_code == 503
    assert response.json()["error_code"] == "rate_limiter_unavailable"
    assert endpoint_body_called is False
    backend_error.assert_called_once_with(
        policy_name=policy.name,
        identifier_kind="unknown",
        error_type="RuntimeUnavailable",
    )
    decision.assert_called_once()
    assert decision.call_args.kwargs["result"] == "runtime_unavailable"
    duration.assert_called_once()
    assert duration.call_args.kwargs["result"] == "runtime_unavailable"
    assert duration.call_args.kwargs["duration_seconds"] >= 0.0


def test_runtime_unavailable_503_contract_is_preserved_when_metrics_fail(
    monkeypatch,
) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=None,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    monkeypatch.setattr(
        rate_limit_metrics.rate_limit_backend_errors_total,
        "add",
        lambda value, attributes=None: (_ for _ in ()).throw(
            RuntimeError("metrics backend down")
        ),
    )
    monkeypatch.setattr(
        rate_limit_metrics.rate_limit_requests_total,
        "add",
        lambda value, attributes=None: (_ for _ in ()).throw(
            RuntimeError("metrics backend down")
        ),
    )
    monkeypatch.setattr(
        rate_limit_metrics.rate_limit_check_duration,
        "record",
        lambda value, attributes=None: (_ for _ in ()).throw(
            RuntimeError("metrics backend down")
        ),
    )

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/protected")

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["error_code"] == "rate_limiter_unavailable"


def test_authenticated_users_have_independent_buckets(monkeypatch) -> None:
    fake = FakeLimiter(allow=True)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)

    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    with client as api_client:
        api_client.get("/api/v1/test/rate-limit/protected")

    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_b
    with client as api_client:
        api_client.get("/api/v1/test/rate-limit/protected")

    assert len(fake.hit_calls) == 2
    _, first_key, *_ = fake.hit_calls[0]
    _, second_key, *_ = fake.hit_calls[1]
    assert first_key != second_key
    assert first_key.startswith("rlid:v1:hmac-sha256:")
    assert second_key.startswith("rlid:v1:hmac-sha256:")
    assert "user-a" not in first_key
    assert "user-b" not in second_key


def test_health_endpoints_are_not_rate_limited(monkeypatch) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    with client as api_client:
        response = api_client.get("/api/v1/health/live")
    assert response.status_code == 200


def test_invite_create_checks_all_layered_policies_before_db(monkeypatch) -> None:
    fake = FakeLimiter(allow_sequence=[True, True, True, True, False])
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    invite_service_cls, user_service_cls, db_session_opened = (
        _install_invite_endpoint_over_limit_guards(client, monkeypatch)
    )

    with client as api_client:
        response = api_client.post(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001/invites",
            json={"email": "Invitee@Example.com", "role": "member"},
        )

    assert response.status_code == 429
    assert [call[0].split(":")[1] for call in fake.hit_calls] == [
        "invite_create",
        "invite_create_organisation",
        "invite_create_organisation_daily",
        "invite_create_target_email",
        "invite_create_target_domain",
    ]
    assert all(
        "Invitee" not in call[0] and "Example.com" not in call[0]
        for call in fake.hit_calls
    )
    assert db_session_opened() is False
    user_service_cls.assert_not_called()
    invite_service_cls.assert_not_called()


def test_invite_resend_checks_all_layered_policies_before_db(monkeypatch) -> None:
    fake = FakeLimiter(allow_sequence=[True, True, False])
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    invite_service_cls, user_service_cls, db_session_opened = (
        _install_invite_endpoint_over_limit_guards(client, monkeypatch)
    )

    with client as api_client:
        response = api_client.post(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001"
            "/invites/00000000-0000-4000-8000-000000000002/resend",
        )

    assert response.status_code == 429
    assert [call[0].split(":")[1] for call in fake.hit_calls] == [
        "invite_mutation",
        "invite_resend_invite",
        "invite_resend_organisation_daily",
    ]
    assert db_session_opened() is False
    user_service_cls.assert_not_called()
    invite_service_cls.assert_not_called()


def _add_invite_layer_probe_routes(client: TestClient) -> None:
    router = APIRouter()

    @router.post("/api/v1/test/layered-invites/{organisation_id}/create")
    async def _create_probe(
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

    @router.post("/api/v1/test/layered-invites/{organisation_id}/{invite_id}/resend")
    async def _resend_probe(
        context: Annotated[
            RateLimitedInviteMutationContext,
            Depends(require_rate_limited_invite_resend_context),
        ],
    ) -> dict[str, str]:
        assert context.principal.external_auth_id
        return {"ok": "true"}

    client.app.include_router(router)


def test_two_actors_share_invite_create_organisation_bucket(monkeypatch) -> None:
    limiter = StatefulLimiter()
    runtime = RateLimiterRuntime(True, object(), limiter, "moving-window")
    client = _build_app(
        monkeypatch,
        enabled=True,
        runtime=runtime,
        policy_limits={"invite_create_organisation": 1},
    )
    _add_invite_layer_probe_routes(client)

    with client as api_client:
        api_client.app.dependency_overrides[get_authenticated_principal] = (
            _principal_user_a
        )
        first = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001/create",
            json={"email": "one@example.com", "role": "member"},
        )
        api_client.app.dependency_overrides[get_authenticated_principal] = (
            _principal_user_b
        )
        second = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001/create",
            json={"email": "two@example.net", "role": "member"},
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "Too many requests."
    assert "organisation" not in second.text.lower()


def test_same_target_email_bucket_is_per_organisation(monkeypatch) -> None:
    limiter = StatefulLimiter()
    runtime = RateLimiterRuntime(True, object(), limiter, "moving-window")
    client = _build_app(
        monkeypatch,
        enabled=True,
        runtime=runtime,
        policy_limits={"invite_create_target_email": 1},
    )
    _add_invite_layer_probe_routes(client)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        same_org_first = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001/create",
            json={"email": "Same@Target.example", "role": "member"},
        )
        same_org_second = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001/create",
            json={"email": "same@target.example", "role": "member"},
        )
        different_org = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000099/create",
            json={"email": "same@target.example", "role": "member"},
        )

    assert same_org_first.status_code == 200
    assert same_org_second.status_code == 429
    assert different_org.status_code == 200


def test_same_target_domain_bucket_is_per_organisation(monkeypatch) -> None:
    limiter = StatefulLimiter()
    runtime = RateLimiterRuntime(True, object(), limiter, "moving-window")
    client = _build_app(
        monkeypatch,
        enabled=True,
        runtime=runtime,
        policy_limits={"invite_create_target_domain": 1},
    )
    _add_invite_layer_probe_routes(client)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        first = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001/create",
            json={"email": "one@example.org", "role": "member"},
        )
        second = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001/create",
            json={"email": "two@example.org", "role": "member"},
        )

    assert first.status_code == 200
    assert second.status_code == 429


def test_invite_resend_bucket_is_per_invite(monkeypatch) -> None:
    limiter = StatefulLimiter()
    runtime = RateLimiterRuntime(True, object(), limiter, "moving-window")
    client = _build_app(
        monkeypatch,
        enabled=True,
        runtime=runtime,
        policy_limits={"invite_resend_invite": 1},
    )
    _add_invite_layer_probe_routes(client)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        first = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001"
            "/00000000-0000-4000-8000-000000000002/resend",
        )
        second = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001"
            "/00000000-0000-4000-8000-000000000002/resend",
        )
        different_invite = api_client.post(
            "/api/v1/test/layered-invites/00000000-0000-4000-8000-000000000001"
            "/00000000-0000-4000-8000-000000000003/resend",
        )

    assert first.status_code == 200
    assert second.status_code == 429
    assert different_invite.status_code == 200


def test_invite_layered_limit_keys_and_errors_do_not_expose_raw_values(
    monkeypatch,
) -> None:
    raw_email = "sensitive@example.test"
    raw_domain = "example.test"
    raw_organisation_id = "00000000-0000-4000-8000-000000000001"
    limiter = StatefulLimiter()
    runtime = RateLimiterRuntime(True, object(), limiter, "moving-window")
    client = _build_app(
        monkeypatch,
        enabled=True,
        runtime=runtime,
        policy_limits={"invite_create_target_email": 1},
    )
    _add_invite_layer_probe_routes(client)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    with client as api_client:
        for _ in range(2):
            response = api_client.post(
                f"/api/v1/test/layered-invites/{raw_organisation_id}/create",
                json={"email": raw_email, "role": "member"},
            )

    assert response.status_code == 429
    combined_redis_material = " ".join(
        f"{namespace} {key}" for namespace, key, _, _ in limiter.hit_calls
    )
    combined_error = response.text
    for raw_value in (raw_email, raw_domain, raw_organisation_id):
        assert raw_value not in combined_redis_material
        assert raw_value not in combined_error


def test_unauthenticated_protected_endpoint_returns_401_before_rate_limiter(
    monkeypatch,
) -> None:
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=FakeLimiter(allow=False),
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)

    with client as api_client:
        response = api_client.post("/api/v1/invites/accept", json={"token": "x"})

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_over_limit_does_not_execute_endpoint_body_or_database_io(monkeypatch) -> None:
    endpoint_body_called = False
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    app = client.app
    app.dependency_overrides[require_authenticated_principal] = _principal_user_a

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.connection = AsyncMock()
    session.begin = MagicMock()
    session.scalar = AsyncMock()
    session.scalars = AsyncMock()
    session.get = AsyncMock()
    session.delete = AsyncMock()
    session.merge = AsyncMock()

    async def _db_override():
        yield session

    app.dependency_overrides[get_db_session] = _db_override

    router = APIRouter()
    policy = RateLimitPolicy(
        name="test_db_guard",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    @router.get(
        "/api/v1/test/rate-limit/db-guard",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe(
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, str]:
        nonlocal endpoint_body_called
        endpoint_body_called = True
        await db_session.execute("select 1")
        return {"ok": "true"}

    app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/db-guard")

    assert response.status_code == 429
    assert len(fake.hit_calls) == 1
    assert endpoint_body_called is False
    session.execute.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    session.refresh.assert_not_called()
    session.connection.assert_not_called()
    session.begin.assert_not_called()
    session.scalar.assert_not_called()
    session.scalars.assert_not_called()
    session.get.assert_not_called()
    session.delete.assert_not_called()
    session.merge.assert_not_called()


def test_unauthenticated_request_returns_401_without_limiter_or_database_io(
    monkeypatch,
) -> None:
    endpoint_body_called = False
    fake = FakeLimiter(allow=False, raise_error=RuntimeError("limiter must not run"))
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    app = client.app

    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.flush = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.connection = AsyncMock()
    session.begin = MagicMock()

    async def _db_override():
        yield session

    app.dependency_overrides[get_db_session] = _db_override

    router = APIRouter()
    policy = RateLimitPolicy(
        name="test_auth_before_rate_limit",
        item=RateLimitItemPerMinute(1),
        fail_open=False,
    )

    @router.get(
        "/api/v1/test/rate-limit/auth-first",
        dependencies=[Depends(rate_limit_dependency(policy))],
    )
    async def _probe(
        db_session: Annotated[AsyncSession, Depends(get_db_session)],
    ) -> dict[str, str]:
        nonlocal endpoint_body_called
        endpoint_body_called = True
        await db_session.execute("select 1")
        return {"ok": "true"}

    app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/auth-first")

    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"
    assert endpoint_body_called is False
    assert len(fake.hit_calls) == 0
    session.execute.assert_not_called()
    session.flush.assert_not_called()
    session.commit.assert_not_called()
    session.refresh.assert_not_called()
    session.connection.assert_not_called()
    session.begin.assert_not_called()


def test_rate_limiting_enablement_does_not_leak_between_apps(monkeypatch) -> None:
    first_client = _build_app(monkeypatch, enabled=True)
    with first_client:
        assert first_client.app.state.rate_limiter_runtime.enabled is False

    second_client = _build_app(monkeypatch, enabled=False)
    with second_client:
        assert second_client.app.state.rate_limiter_runtime.enabled is False


def test_invite_policies_are_distinct_and_declarative() -> None:
    assert INVITE_ACCEPT_POLICY.name == "invite_accept"
    assert INVITE_ACCEPT_POLICY.default_limit == 5
    assert INVITE_ACCEPT_POLICY.default_window_seconds == 300
    assert INVITE_ACCEPT_POLICY.default_fail_open is False
    assert INVITE_ACCEPT_POLICY.sensitivity == "critical"

    assert INVITE_CREATE_POLICY.name == "invite_create"
    assert INVITE_CREATE_POLICY.default_limit == 20
    assert INVITE_CREATE_POLICY.default_window_seconds == 3600
    assert INVITE_CREATE_POLICY.default_fail_open is False
    assert INVITE_CREATE_POLICY.sensitivity == "sensitive"


def test_runtime_code_uses_limits_aio_namespace() -> None:
    from app.core.rate_limit import dependencies, lifecycle

    dependency_source = inspect.getsource(dependencies)
    lifecycle_source = inspect.getsource(lifecycle)

    assert "limits.aio" in dependency_source or "limits.aio" in lifecycle_source


def test_env_override_changes_effective_policy_threshold(monkeypatch) -> None:
    monkeypatch.setenv("RATE_LIMITING__POLICIES__TENANT_WRITE__LIMIT", "7")
    monkeypatch.setenv("RATE_LIMITING__POLICIES__TENANT_WRITE__WINDOW_SECONDS", "300")

    fake = FakeLimiter(allow=True)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    router = APIRouter()

    @router.get(
        "/api/v1/test/rate-limit/tenant-write-effective",
        dependencies=[Depends(rate_limit_dependency(TENANT_WRITE_POLICY))],
    )
    async def _tenant_write_probe() -> dict[str, str]:
        return {"ok": "true"}

    client.app.include_router(router)

    with client as api_client:
        response = api_client.get("/api/v1/test/rate-limit/tenant-write-effective")

    assert response.status_code == 200
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("test-rl:tenant_write:")
    assert fake.hit_calls[0][2] == 7
    assert fake.hit_expiries[0] == 300
    assert TENANT_WRITE_POLICY.default_limit == 30
    assert TENANT_WRITE_POLICY.default_window_seconds == 60


def test_over_limit_tenant_write_returns_429_before_db_or_service(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    async def _db_session_should_not_open():
        raise AssertionError("tenant write opened a DB session before rate limiting")
        yield  # pragma: no cover

    service_cls = MagicMock()
    client.app.dependency_overrides[get_db_session] = _db_session_should_not_open
    monkeypatch.setattr(
        "app.organisations.api.organisations.OrganisationService", service_cls
    )

    with client as api_client:
        response = api_client.patch(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001",
            json={"name": "Blocked Ltd"},
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert fake.hit_calls[0][0].startswith("test-rl:tenant_write:")
    service_cls.assert_not_called()


def test_over_limit_platform_audit_read_returns_429_before_db_or_service(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    async def _db_session_should_not_open():
        raise AssertionError("audit read opened a DB session before rate limiting")
        yield  # pragma: no cover

    list_events = AsyncMock()
    client.app.dependency_overrides[get_db_session] = _db_session_should_not_open
    monkeypatch.setattr(
        "app.audit.services.audit_events.AuditEventService.list_events", list_events
    )

    with client as api_client:
        response = api_client.get("/api/v1/platform/audit-events")

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert fake.hit_calls[0][0].startswith("test-rl:audit_read:")
    list_events.assert_not_called()


def test_over_limit_organisation_create_returns_429_before_db_or_onboarding(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a

    async def _db_session_should_not_open():
        raise AssertionError(
            "organisation create opened a DB session before rate limiting"
        )
        yield  # pragma: no cover

    onboarding_cls = MagicMock()
    client.app.dependency_overrides[get_db_session] = _db_session_should_not_open
    monkeypatch.setattr(
        "app.organisations.api.organisations.OnboardingService", onboarding_cls
    )

    with client as api_client:
        response = api_client.post(
            "/api/v1/organisations",
            json={"name": "Blocked Ltd", "slug": "blocked-ltd"},
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert fake.hit_calls[0][0].startswith("test-rl:organisation_create:")
    onboarding_cls.assert_not_called()


def test_over_limit_invite_create_returns_429_before_db_or_service(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    invite_service_cls, user_service_cls, db_session_opened = (
        _install_invite_endpoint_over_limit_guards(client, monkeypatch)
    )

    with client as api_client:
        response = api_client.post(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001/invites",
            json={"email": "invitee@example.com", "role": "member"},
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("test-rl:invite_create:")
    assert db_session_opened() is False
    user_service_cls.assert_not_called()
    invite_service_cls.assert_not_called()


def test_over_limit_invite_accept_returns_429_before_db_or_service(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    invite_service_cls, user_service_cls, db_session_opened = (
        _install_invite_endpoint_over_limit_guards(client, monkeypatch)
    )

    with client as api_client:
        response = api_client.post(
            "/api/v1/invites/accept",
            json={"token": "valid-invite-token"},
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("test-rl:invite_accept:")
    assert db_session_opened() is False
    invite_service_cls.assert_not_called()
    user_service_cls.assert_not_called()


def test_over_limit_invite_resend_returns_429_before_db_or_service(monkeypatch) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)
    client.app.dependency_overrides[get_authenticated_principal] = _principal_user_a
    invite_service_cls, user_service_cls, db_session_opened = (
        _install_invite_endpoint_over_limit_guards(client, monkeypatch)
    )

    with client as api_client:
        response = api_client.post(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001"
            "/invites/00000000-0000-4000-8000-000000000002/resend",
        )

    assert response.status_code == 429
    assert response.json()["error_code"] == "rate_limited"
    assert len(fake.hit_calls) == 1
    assert fake.hit_calls[0][0].startswith("test-rl:invite_mutation:")
    assert db_session_opened() is False
    user_service_cls.assert_not_called()
    invite_service_cls.assert_not_called()


def test_unauthenticated_protected_endpoint_returns_401_before_rate_limit(
    monkeypatch,
) -> None:
    fake = FakeLimiter(allow=False)
    runtime = RateLimiterRuntime(
        enabled=True,
        storage=object(),
        limiter=fake,
        strategy_name="moving-window",
    )
    client = _build_app(monkeypatch, enabled=True, runtime=runtime)

    with client as api_client:
        response = api_client.patch(
            "/api/v1/organisations/00000000-0000-4000-8000-000000000001",
            json={"name": "Blocked Ltd"},
        )

    assert response.status_code == 401
    assert fake.hit_calls == []

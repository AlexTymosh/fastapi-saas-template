from __future__ import annotations

from unittest.mock import AsyncMock
from uuid import uuid4

import anyio
import pytest
from starlette.requests import Request

from app.core.auth import AuthenticatedPrincipal
from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_MUTATION_POLICY,
)
from app.invites.api import rate_limits
from app.invites.schemas.invites import AcceptInviteRequest, CreateInviteRequest
from app.memberships.models.membership import MembershipRole

pytestmark = [pytest.mark.security]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/test",
            "headers": [],
            "client": ("203.0.113.10", 12345),
        }
    )


def _principal() -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id="user-a",
        email="user-a@example.com",
        email_verified=True,
    )


def test_invite_create_dependency_applies_only_actor_bucket_before_authorization(
    monkeypatch,
) -> None:
    async def _run() -> None:
        check_rate_limit = AsyncMock()
        monkeypatch.setattr(rate_limits, "check_rate_limit", check_rate_limit)

        payload = CreateInviteRequest(
            email="Invitee@Example.com",
            role=MembershipRole.MEMBER,
        )
        principal = _principal()
        request = _request()

        context = await rate_limits.require_rate_limited_invite_create_context(
            organisation_id=uuid4(),
            payload=payload,
            request=request,
            principal=principal,
        )

        assert context.principal is principal
        assert context.payload is payload
        check_rate_limit.assert_awaited_once_with(
            request=request,
            principal=principal,
            policy=INVITE_CREATE_POLICY,
        )

    anyio.run(_run)


def test_invite_accept_dependency_applies_actor_and_token_fingerprint_buckets(
    monkeypatch,
) -> None:
    async def _run() -> None:
        check_rate_limit = AsyncMock()
        check_token_bucket = AsyncMock()
        monkeypatch.setattr(rate_limits, "check_rate_limit", check_rate_limit)
        monkeypatch.setattr(
            rate_limits,
            "check_invite_accept_token_rate_limit",
            check_token_bucket,
        )

        payload = AcceptInviteRequest(token="raw-token-value")
        principal = _principal()
        request = _request()

        context = await rate_limits.require_rate_limited_invite_accept_context(
            payload=payload,
            request=request,
            principal=principal,
        )

        assert context.principal is principal
        assert context.payload is payload
        check_rate_limit.assert_awaited_once_with(
            request=request,
            principal=principal,
            policy=INVITE_ACCEPT_POLICY,
        )
        check_token_bucket.assert_awaited_once_with(
            request=request,
            token="raw-token-value",
        )

    anyio.run(_run)


def test_invite_resend_dependency_applies_only_actor_bucket_before_authorization(
    monkeypatch,
) -> None:
    async def _run() -> None:
        check_rate_limit = AsyncMock()
        monkeypatch.setattr(rate_limits, "check_rate_limit", check_rate_limit)

        principal = _principal()
        request = _request()

        context = await rate_limits.require_rate_limited_invite_resend_context(
            organisation_id=uuid4(),
            invite_id=uuid4(),
            request=request,
            principal=principal,
        )

        assert context.principal is principal
        check_rate_limit.assert_awaited_once_with(
            request=request,
            principal=principal,
            policy=INVITE_MUTATION_POLICY,
        )

    anyio.run(_run)

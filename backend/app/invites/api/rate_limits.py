from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import Depends, Request

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.rate_limit.business import check_invite_accept_token_rate_limit
from app.core.rate_limit.dependencies import check_rate_limit
from app.core.rate_limit.policies import (
    INVITE_ACCEPT_POLICY,
    INVITE_ACCEPT_TOKEN_POLICY,
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_CREATE_TARGET_DOMAIN_POLICY,
    INVITE_CREATE_TARGET_EMAIL_POLICY,
    INVITE_MUTATION_POLICY,
    INVITE_RESEND_INVITE_POLICY,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY,
)
from app.invites.schemas.invites import AcceptInviteRequest, CreateInviteRequest


@dataclass(frozen=True)
class InviteCreateRateLimitContext:
    principal: AuthenticatedPrincipal
    payload: CreateInviteRequest


@dataclass(frozen=True)
class InviteAcceptRateLimitContext:
    principal: AuthenticatedPrincipal
    payload: AcceptInviteRequest


@dataclass(frozen=True)
class InviteResendRateLimitContext:
    principal: AuthenticatedPrincipal


PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]


async def require_rate_limited_invite_create_context(
    organisation_id: UUID,
    payload: CreateInviteRequest,
    request: Request,
    principal: PrincipalDep,
) -> InviteCreateRateLimitContext:
    del organisation_id
    await check_rate_limit(
        request=request,
        principal=principal,
        policy=INVITE_CREATE_POLICY,
    )
    return InviteCreateRateLimitContext(principal=principal, payload=payload)


async def require_rate_limited_invite_accept_context(
    payload: AcceptInviteRequest,
    request: Request,
    principal: PrincipalDep,
) -> InviteAcceptRateLimitContext:
    await check_rate_limit(
        request=request,
        principal=principal,
        policy=INVITE_ACCEPT_POLICY,
    )
    await check_invite_accept_token_rate_limit(
        request=request,
        token=payload.token,
    )
    return InviteAcceptRateLimitContext(principal=principal, payload=payload)


async def require_rate_limited_invite_resend_context(
    organisation_id: UUID,
    invite_id: UUID,
    request: Request,
    principal: PrincipalDep,
) -> InviteResendRateLimitContext:
    del organisation_id, invite_id
    await check_rate_limit(
        request=request,
        principal=principal,
        policy=INVITE_MUTATION_POLICY,
    )
    return InviteResendRateLimitContext(principal=principal)


_create_context = cast(Any, require_rate_limited_invite_create_context)
_accept_context = cast(Any, require_rate_limited_invite_accept_context)
_resend_context = cast(Any, require_rate_limited_invite_resend_context)

# Route metadata intentionally declares all policies protecting the endpoint
# across the full request lifecycle. Only the actor bucket runs in this API
# dependency; business-scope buckets run later in InviteService after tenant
# authorization, which avoids cross-tenant quota poisoning.
_create_context.__rate_limit_policy_names__ = (
    INVITE_CREATE_POLICY.name,
    INVITE_CREATE_ORGANISATION_POLICY.name,
    INVITE_CREATE_ORGANISATION_DAILY_POLICY.name,
    INVITE_CREATE_TARGET_EMAIL_POLICY.name,
    INVITE_CREATE_TARGET_DOMAIN_POLICY.name,
)
_create_context.__rate_limit_policy_name__ = INVITE_CREATE_POLICY.name
_accept_context.__rate_limit_policy_names__ = (
    INVITE_ACCEPT_POLICY.name,
    INVITE_ACCEPT_TOKEN_POLICY.name,
)
_accept_context.__rate_limit_policy_name__ = INVITE_ACCEPT_POLICY.name
_resend_context.__rate_limit_policy_names__ = (
    INVITE_MUTATION_POLICY.name,
    INVITE_RESEND_INVITE_POLICY.name,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY.name,
)
_resend_context.__rate_limit_policy_name__ = INVITE_MUTATION_POLICY.name

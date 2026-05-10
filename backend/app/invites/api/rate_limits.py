from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.rate_limit.dependencies import (
    check_rate_limit,
    check_rate_limits_for_buckets,
)
from app.core.rate_limit.identifiers import RateLimitBucket
from app.core.rate_limit.policies import (
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_CREATE_TARGET_DOMAIN_POLICY,
    INVITE_CREATE_TARGET_EMAIL_POLICY,
    INVITE_MUTATION_POLICY,
    INVITE_RESEND_INVITE_POLICY,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY,
)
from app.invites.schemas.invites import CreateInviteRequest


@dataclass(frozen=True)
class InviteCreateRateLimitContext:
    principal: AuthenticatedPrincipal
    payload: CreateInviteRequest


@dataclass(frozen=True)
class InviteResendRateLimitContext:
    principal: AuthenticatedPrincipal


PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]


def _normalised_email(payload: CreateInviteRequest) -> str:
    return str(payload.email).strip().lower()


def _domain_from_email(normalised_email: str) -> str:
    return normalised_email.rsplit("@", maxsplit=1)[1].lower()


async def require_rate_limited_invite_create_context(
    organisation_id: UUID,
    payload: CreateInviteRequest,
    request: Request,
    principal: PrincipalDep,
) -> InviteCreateRateLimitContext:
    normalised_email = _normalised_email(payload)
    normalised_domain = _domain_from_email(normalised_email)
    organisation_raw = f"organisation:{organisation_id}"

    await check_rate_limit(
        request=request,
        principal=principal,
        policy=INVITE_CREATE_POLICY,
    )
    await check_rate_limits_for_buckets(
        request=request,
        checks=[
            (
                INVITE_CREATE_ORGANISATION_POLICY,
                RateLimitBucket(
                    kind="organisation",
                    raw_value=organisation_raw,
                ),
            ),
            (
                INVITE_CREATE_ORGANISATION_DAILY_POLICY,
                RateLimitBucket(
                    kind="organisation",
                    raw_value=organisation_raw,
                ),
            ),
            (
                INVITE_CREATE_TARGET_EMAIL_POLICY,
                RateLimitBucket(
                    kind="organisation_target_email",
                    raw_value=(
                        f"organisation:{organisation_id}:email:{normalised_email}"
                    ),
                ),
            ),
            (
                INVITE_CREATE_TARGET_DOMAIN_POLICY,
                RateLimitBucket(
                    kind="organisation_target_domain",
                    raw_value=(
                        f"organisation:{organisation_id}:domain:{normalised_domain}"
                    ),
                ),
            ),
        ],
    )
    return InviteCreateRateLimitContext(principal=principal, payload=payload)


async def require_rate_limited_invite_resend_context(
    organisation_id: UUID,
    invite_id: UUID,
    request: Request,
    principal: PrincipalDep,
) -> InviteResendRateLimitContext:
    await check_rate_limit(
        request=request,
        principal=principal,
        policy=INVITE_MUTATION_POLICY,
    )
    await check_rate_limits_for_buckets(
        request=request,
        checks=[
            (
                INVITE_RESEND_INVITE_POLICY,
                RateLimitBucket(
                    kind="invite",
                    raw_value=f"organisation:{organisation_id}:invite:{invite_id}",
                ),
            ),
            (
                INVITE_RESEND_ORGANISATION_DAILY_POLICY,
                RateLimitBucket(
                    kind="organisation",
                    raw_value=f"organisation:{organisation_id}",
                ),
            ),
        ],
    )
    return InviteResendRateLimitContext(principal=principal)


require_rate_limited_invite_create_context.__rate_limit_policy_names__ = (  # type: ignore[attr-defined]
    INVITE_CREATE_POLICY.name,
    INVITE_CREATE_ORGANISATION_POLICY.name,
    INVITE_CREATE_ORGANISATION_DAILY_POLICY.name,
    INVITE_CREATE_TARGET_EMAIL_POLICY.name,
    INVITE_CREATE_TARGET_DOMAIN_POLICY.name,
)
require_rate_limited_invite_create_context.__rate_limit_policy_name__ = (  # type: ignore[attr-defined]
    INVITE_CREATE_POLICY.name
)
require_rate_limited_invite_resend_context.__rate_limit_policy_names__ = (  # type: ignore[attr-defined]
    INVITE_MUTATION_POLICY.name,
    INVITE_RESEND_INVITE_POLICY.name,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY.name,
)
require_rate_limited_invite_resend_context.__rate_limit_policy_name__ = (  # type: ignore[attr-defined]
    INVITE_MUTATION_POLICY.name
)

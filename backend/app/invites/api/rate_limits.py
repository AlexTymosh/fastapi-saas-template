from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.rate_limit import (
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    INVITE_CREATE_POLICY,
    INVITE_CREATE_TARGET_DOMAIN_POLICY,
    INVITE_CREATE_TARGET_EMAIL_POLICY,
    INVITE_MUTATION_POLICY,
    INVITE_RESEND_INVITE_POLICY,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY,
    check_rate_limit,
    check_rate_limits_for_buckets,
)
from app.core.rate_limit.identifiers import RateLimitBucket
from app.invites.schemas.invites import CreateInviteRequest


@dataclass(frozen=True)
class RateLimitedInviteCreateContext:
    principal: AuthenticatedPrincipal
    payload: CreateInviteRequest


@dataclass(frozen=True)
class RateLimitedInviteMutationContext:
    principal: AuthenticatedPrincipal


PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]


def _normalise_email(value: object) -> str:
    return str(value).strip().lower()


def _domain_from_email(normalised_email: str) -> str:
    return normalised_email.rsplit("@", maxsplit=1)[1].lower()


def _organisation_bucket(organisation_id: UUID) -> RateLimitBucket:
    return RateLimitBucket(
        kind="organisation",
        raw_value=f"organisation:{organisation_id}",
    )


def _organisation_target_email_bucket(
    *, organisation_id: UUID, normalised_email: str
) -> RateLimitBucket:
    return RateLimitBucket(
        kind="organisation_target_email",
        raw_value=f"organisation:{organisation_id}:email:{normalised_email}",
    )


def _organisation_target_domain_bucket(
    *, organisation_id: UUID, normalised_domain: str
) -> RateLimitBucket:
    return RateLimitBucket(
        kind="organisation_target_domain",
        raw_value=f"organisation:{organisation_id}:domain:{normalised_domain}",
    )


def _invite_bucket(*, organisation_id: UUID, invite_id: UUID) -> RateLimitBucket:
    return RateLimitBucket(
        kind="invite",
        raw_value=f"organisation:{organisation_id}:invite:{invite_id}",
    )


async def require_rate_limited_invite_create_context(
    organisation_id: UUID,
    payload: CreateInviteRequest,
    request: Request,
    principal: PrincipalDep,
) -> RateLimitedInviteCreateContext:
    normalised_email = _normalise_email(payload.email)
    normalised_domain = _domain_from_email(normalised_email)

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
                _organisation_bucket(organisation_id),
            ),
            (
                INVITE_CREATE_ORGANISATION_DAILY_POLICY,
                _organisation_bucket(organisation_id),
            ),
            (
                INVITE_CREATE_TARGET_EMAIL_POLICY,
                _organisation_target_email_bucket(
                    organisation_id=organisation_id,
                    normalised_email=normalised_email,
                ),
            ),
            (
                INVITE_CREATE_TARGET_DOMAIN_POLICY,
                _organisation_target_domain_bucket(
                    organisation_id=organisation_id,
                    normalised_domain=normalised_domain,
                ),
            ),
        ],
    )
    return RateLimitedInviteCreateContext(principal=principal, payload=payload)


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


async def require_rate_limited_invite_resend_context(
    organisation_id: UUID,
    invite_id: UUID,
    request: Request,
    principal: PrincipalDep,
) -> RateLimitedInviteMutationContext:
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
                _invite_bucket(organisation_id=organisation_id, invite_id=invite_id),
            ),
            (
                INVITE_RESEND_ORGANISATION_DAILY_POLICY,
                _organisation_bucket(organisation_id),
            ),
        ],
    )
    return RateLimitedInviteMutationContext(principal=principal)


require_rate_limited_invite_resend_context.__rate_limit_policy_names__ = (  # type: ignore[attr-defined]
    INVITE_MUTATION_POLICY.name,
    INVITE_RESEND_INVITE_POLICY.name,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY.name,
)
require_rate_limited_invite_resend_context.__rate_limit_policy_name__ = (  # type: ignore[attr-defined]
    INVITE_MUTATION_POLICY.name
)

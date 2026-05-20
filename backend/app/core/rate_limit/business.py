from __future__ import annotations

from collections.abc import Awaitable, Callable
from hashlib import sha256
from uuid import UUID

from fastapi import Request

from app.core.rate_limit.dependencies import (
    check_rate_limit_for_bucket,
    check_rate_limits_for_buckets,
)
from app.core.rate_limit.identifiers import RateLimitBucket
from app.core.rate_limit.policies import (
    INVITE_ACCEPT_TOKEN_POLICY,
    INVITE_CREATE_ORGANISATION_DAILY_POLICY,
    INVITE_CREATE_ORGANISATION_POLICY,
    INVITE_CREATE_TARGET_DOMAIN_POLICY,
    INVITE_CREATE_TARGET_EMAIL_POLICY,
    INVITE_RESEND_INVITE_POLICY,
    INVITE_RESEND_ORGANISATION_DAILY_POLICY,
    TENANT_WRITE_ORGANISATION_POLICY,
)

BusinessRateLimiter = Callable[[], Awaitable[None]]


def _normalised_email(value: str) -> str:
    return value.strip().lower()


def _domain_from_email(normalised_email: str) -> str:
    return normalised_email.rsplit("@", maxsplit=1)[1].lower()


def _token_fingerprint(token: str) -> str:
    return sha256(token.strip().encode("utf-8")).hexdigest()


async def check_invite_accept_token_rate_limit(
    *,
    request: Request,
    token: str,
) -> None:
    """Apply a token-fingerprint bucket without exposing the raw invite token.

    The Redis key is still HMAC-protected by `build_bucket_identifier()`; the
    raw value is a one-way SHA-256 fingerprint rather than the token itself so
    accidental instrumentation/debugging cannot surface the original secret.
    """
    await check_rate_limit_for_bucket(
        request=request,
        policy=INVITE_ACCEPT_TOKEN_POLICY,
        bucket=RateLimitBucket(
            kind="invite_accept_token",
            raw_value=f"token_sha256:{_token_fingerprint(token)}",
        ),
    )


async def check_authorized_tenant_write_business_rate_limit(
    *,
    request: Request,
    organisation_id: UUID,
) -> None:
    """Apply an organisation-wide tenant-write bucket after authorization.

    Actor-level TENANT_WRITE_POLICY remains an endpoint dependency and protects
    the API before DB access. This business-scope bucket must run only after the
    service layer has proved that the actor can mutate the target organisation,
    otherwise outsiders could poison a victim tenant's quota.
    """
    await check_rate_limit_for_bucket(
        request=request,
        policy=TENANT_WRITE_ORGANISATION_POLICY,
        bucket=RateLimitBucket(
            kind="organisation",
            raw_value=f"organisation:{organisation_id}",
        ),
    )


async def check_authorized_invite_create_business_rate_limits(
    *,
    request: Request,
    organisation_id: UUID,
    email: str,
) -> None:
    normalised_email = _normalised_email(email)
    normalised_domain = _domain_from_email(normalised_email)
    organisation_raw = f"organisation:{organisation_id}"

    await check_rate_limits_for_buckets(
        request=request,
        checks=[
            (
                INVITE_CREATE_ORGANISATION_POLICY,
                RateLimitBucket(kind="organisation", raw_value=organisation_raw),
            ),
            (
                INVITE_CREATE_ORGANISATION_DAILY_POLICY,
                RateLimitBucket(kind="organisation", raw_value=organisation_raw),
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


async def check_authorized_invite_resend_business_rate_limits(
    *,
    request: Request,
    organisation_id: UUID,
    invite_id: UUID,
) -> None:
    await check_rate_limits_for_buckets(
        request=request,
        checks=[
            (
                INVITE_RESEND_INVITE_POLICY,
                RateLimitBucket(
                    kind="invite",
                    raw_value=(f"organisation:{organisation_id}:invite:{invite_id}"),
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

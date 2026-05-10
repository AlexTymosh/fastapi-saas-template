from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol

from fastapi import Request

from app.core.auth import AuthenticatedPrincipal

_BUCKET_KEY_PREFIX = "rlid:v1:hmac-sha256"
_FALLBACK_IP = "0.0.0.0"


class _SecretValue(Protocol):
    def get_secret_value(self) -> str: ...


@dataclass(frozen=True)
class RateLimitIdentifier:
    kind: str
    bucket_key: str


def build_identifier(
    *,
    principal: AuthenticatedPrincipal | None,
    request: Request,
    trust_proxy_headers: bool,
    identifier_secret: str | _SecretValue,
) -> RateLimitIdentifier:
    if principal is not None:
        return RateLimitIdentifier(
            kind="user",
            bucket_key=_build_bucket_key(
                secret=identifier_secret,
                message=f"user:{principal.external_auth_id}",
            ),
        )

    ip_value = resolve_client_ip(
        request=request,
        trust_proxy_headers=trust_proxy_headers,
    )
    return RateLimitIdentifier(
        kind="ip",
        bucket_key=_build_bucket_key(
            secret=identifier_secret,
            message=f"ip:{ip_value}",
        ),
    )


def resolve_client_ip(*, request: Request, trust_proxy_headers: bool) -> str:
    if not trust_proxy_headers:
        return _normalise_ip(request.client.host if request.client else None)

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        first_hop = x_forwarded_for.split(",", maxsplit=1)[0].strip()
        normalised = _normalise_ip(first_hop)
        if normalised != _FALLBACK_IP:
            return normalised

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        normalised = _normalise_ip(x_real_ip)
        if normalised != _FALLBACK_IP:
            return normalised

    return _normalise_ip(request.client.host if request.client else None)


def _normalise_ip(value: str | None) -> str:
    candidate = (value or "").strip()
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return _FALLBACK_IP
    # TODO: consider truncating IPv6 client identifiers to /64 to reduce bypass
    # risk from IPv6 address rotation.
    return address.compressed


def _build_bucket_key(*, secret: str | _SecretValue, message: str) -> str:
    secret_value = (
        secret.get_secret_value() if hasattr(secret, "get_secret_value") else secret
    )
    digest = hmac.new(
        str(secret_value).encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).hexdigest()
    return f"{_BUCKET_KEY_PREFIX}:{digest}"

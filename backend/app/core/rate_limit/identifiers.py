from __future__ import annotations

import hashlib
import ipaddress
from dataclasses import dataclass

from fastapi import Request

from app.core.auth import AuthenticatedPrincipal


@dataclass(frozen=True)
class RateLimitIdentifier:
    kind: str
    hashed_value: str


def build_identifier(
    *,
    principal: AuthenticatedPrincipal | None,
    request: Request,
    trust_proxy_headers: bool,
) -> RateLimitIdentifier:
    if principal is not None:
        return RateLimitIdentifier(
            kind="user",
            hashed_value=_hash_value(principal.external_auth_id),
        )

    ip_value = resolve_client_ip(
        request=request,
        trust_proxy_headers=trust_proxy_headers,
    )
    return RateLimitIdentifier(kind="ip", hashed_value=_hash_value(ip_value))


def resolve_client_ip(*, request: Request, trust_proxy_headers: bool) -> str:
    if not trust_proxy_headers:
        return _normalize_ip(request.client.host if request.client else None)

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        first_hop = x_forwarded_for.split(",", maxsplit=1)[0].strip()
        if _is_valid_ip(first_hop):
            return first_hop

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip and _is_valid_ip(x_real_ip.strip()):
        return x_real_ip.strip()

    return _normalize_ip(request.client.host if request.client else None)


def _normalize_ip(value: str | None) -> str:
    candidate = (value or "").strip()
    if _is_valid_ip(candidate):
        return candidate
    return "0.0.0.0"


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

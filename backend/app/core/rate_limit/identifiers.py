from __future__ import annotations

import hashlib
import ipaddress

from fastapi import Request

from app.core.auth import AuthenticatedPrincipal
from app.core.config.settings import RateLimitingSettings


def _hash_identifier(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:32]


def _extract_proxy_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        first_hop = forwarded_for.split(",", maxsplit=1)[0].strip()
        if _is_valid_ip(first_hop):
            return first_hop

    real_ip = request.headers.get("X-Real-IP")
    if real_ip and _is_valid_ip(real_ip.strip()):
        return real_ip.strip()

    return None


def _is_valid_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def resolve_client_ip(request: Request, settings: RateLimitingSettings) -> str:
    if settings.trust_proxy_headers:
        proxy_ip = _extract_proxy_ip(request)
        if proxy_ip is not None:
            return proxy_ip

    if request.client and request.client.host and _is_valid_ip(request.client.host):
        return request.client.host

    return "0.0.0.0"


def build_key_identifier(
    *,
    principal: AuthenticatedPrincipal | None,
    request: Request,
    settings: RateLimitingSettings,
) -> tuple[str, str]:
    if principal is not None:
        return "user", _hash_identifier(principal.external_auth_id)

    ip = resolve_client_ip(request, settings)
    return "ip", _hash_identifier(ip)

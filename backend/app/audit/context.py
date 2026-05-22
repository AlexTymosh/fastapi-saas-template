from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import SecretStr
from starlette.requests import Request

from app.core.rate_limit.identifiers import is_request_from_trusted_proxy


@dataclass(frozen=True, slots=True)
class AuditContext:
    actor_user_id: UUID | None
    ip_address: str | None = None
    user_agent: str | None = None
    network_identifier_secret: SecretStr | None = None


def build_audit_context_from_request(
    *,
    actor_user_id: UUID | None,
    request: Request,
) -> AuditContext:
    return AuditContext(
        actor_user_id=actor_user_id,
        ip_address=_audit_client_ip_from_request(request),
        user_agent=request.headers.get("user-agent"),
        network_identifier_secret=_audit_network_identifier_secret_from_request(
            request
        ),
    )


def _settings_from_request(request: Request) -> Any | None:
    app = request.scope.get("app")
    state = getattr(app, "state", None)
    return getattr(state, "settings", None)


def _audit_client_ip_from_request(request: Request) -> str | None:
    """Return an audit-safe raw client IP candidate or None.

    Rate-limit identifiers intentionally coerce invalid client hosts to a stable
    sentinel so buckets remain deterministic. Audit attribution should not do
    that: if ASGI exposes a non-IP peer host, persisting a fake 0.0.0.0/24
    network would be misleading. Invalid peer values are therefore discarded.
    """

    peer_ip = _normalise_audit_ip(request.client.host if request.client else None)
    if peer_ip is None:
        return None

    settings = _settings_from_request(request)
    rate_limiting_settings = getattr(settings, "rate_limiting", None)
    trust_proxy_headers = bool(
        getattr(rate_limiting_settings, "trust_proxy_headers", False)
    )
    trusted_proxy_cidrs = getattr(
        rate_limiting_settings,
        "trusted_proxy_cidrs",
        None,
    )

    if not trust_proxy_headers or not is_request_from_trusted_proxy(
        request=request,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    ):
        return peer_ip

    return _forwarded_audit_client_ip(request) or peer_ip


def _forwarded_audit_client_ip(request: Request) -> str | None:
    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        first_hop = x_forwarded_for.split(",", maxsplit=1)[0].strip()
        forwarded_ip = _normalise_audit_ip(first_hop)
        if forwarded_ip is not None:
            return forwarded_ip

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        return _normalise_audit_ip(x_real_ip)

    return None


def _normalise_audit_ip(value: str | None) -> str | None:
    candidate = (value or "").strip()
    try:
        return ipaddress.ip_address(candidate).compressed
    except ValueError:
        return None


def _audit_network_identifier_secret_from_request(
    request: Request,
) -> SecretStr | None:
    settings = _settings_from_request(request)
    audit_settings = getattr(settings, "audit", None)
    secret = getattr(audit_settings, "network_identifier_secret", None)
    return secret if isinstance(secret, SecretStr) else None

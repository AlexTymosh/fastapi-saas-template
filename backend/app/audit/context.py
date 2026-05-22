from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from pydantic import SecretStr
from starlette.requests import Request

from app.core.rate_limit.identifiers import resolve_client_ip


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
    if request.client is None:
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

    return resolve_client_ip(
        request=request,
        trust_proxy_headers=trust_proxy_headers,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    )


def _audit_network_identifier_secret_from_request(
    request: Request,
) -> SecretStr | None:
    settings = _settings_from_request(request)
    audit_settings = getattr(settings, "audit", None)
    secret = getattr(audit_settings, "network_identifier_secret", None)
    return secret if isinstance(secret, SecretStr) else None

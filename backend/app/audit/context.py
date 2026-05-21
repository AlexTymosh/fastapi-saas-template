from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from pydantic import SecretStr
from starlette.requests import Request


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
    client_host = request.client.host if request.client is not None else None
    return AuditContext(
        actor_user_id=actor_user_id,
        ip_address=client_host,
        user_agent=request.headers.get("user-agent"),
        network_identifier_secret=_audit_network_identifier_secret_from_request(
            request
        ),
    )


def _audit_network_identifier_secret_from_request(
    request: Request,
) -> SecretStr | None:
    app = request.scope.get("app")
    state = getattr(app, "state", None)
    settings = getattr(state, "settings", None)
    audit_settings = getattr(settings, "audit", None)
    secret = getattr(audit_settings, "network_identifier_secret", None)
    return secret if isinstance(secret, SecretStr) else None

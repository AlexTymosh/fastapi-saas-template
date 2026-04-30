from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from starlette.requests import Request


@dataclass(frozen=True, slots=True)
class AuditContext:
    actor_user_id: UUID | None
    ip_address: str | None = None
    user_agent: str | None = None


def build_audit_context_from_request(
    *,
    actor_user_id: UUID | None,
    request: Request,
) -> AuditContext:
    client_host = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    return AuditContext(
        actor_user_id=actor_user_id,
        ip_address=client_host,
        user_agent=user_agent,
    )

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import (
    AuditAction,
    AuditCategory,
    AuditEvent,
    AuditTargetType,
)
from app.audit.repositories.audit_events import AuditEventRepository

_FORBIDDEN_METADATA_KEYS = {
    "token",
    "raw_token",
    "invite_token",
    "token_hash",
    "authorization",
    "password",
    "secret",
    "api_key",
    "headers",
    "cookie",
    "set_cookie",
}


class AuditEventService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = AuditEventRepository(session)

    async def record_event(
        self,
        *,
        audit_context: AuditContext,
        category: AuditCategory,
        action: AuditAction,
        target_type: AuditTargetType,
        target_id: UUID | None,
        reason: str | None = None,
        metadata_json: dict[str, object] | None = None,
    ) -> AuditEvent:
        validated_metadata = _validate_metadata_json(metadata_json)
        user_agent = audit_context.user_agent
        if user_agent is not None:
            user_agent = user_agent[:512]

        return await self.repository.create(
            actor_user_id=audit_context.actor_user_id,
            category=category,
            action=action,
            target_type=target_type,
            target_id=target_id,
            reason=reason,
            metadata_json=validated_metadata,
            ip_address=audit_context.ip_address,
            user_agent=user_agent,
        )


def _validate_metadata_json(
    metadata_json: dict[str, object] | None,
) -> dict[str, object] | None:
    if metadata_json is None:
        return None
    _validate_no_forbidden_metadata_keys(metadata_json)
    if _calculate_json_depth(metadata_json) > 3:
        raise ValueError("Audit metadata nesting depth exceeds maximum")
    encoded = json.dumps(metadata_json, separators=(",", ":"), ensure_ascii=False)
    if len(encoded.encode("utf-8")) > 8192:
        raise ValueError("Audit metadata exceeds maximum size")
    return metadata_json


def _calculate_json_depth(value: object) -> int:
    if isinstance(value, dict):
        if not value:
            return 1
        return 1 + max(_calculate_json_depth(item) for item in value.values())
    if isinstance(value, list):
        if not value:
            return 1
        return 1 + max(_calculate_json_depth(item) for item in value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return 1
    raise ValueError("Audit metadata contains unsupported value type")


def _validate_no_forbidden_metadata_keys(metadata_json: dict[str, object]) -> None:
    for key, value in metadata_json.items():
        lowered_key = key.lower()
        if lowered_key in _FORBIDDEN_METADATA_KEYS:
            raise ValueError(f"Forbidden metadata key: {key}")
        if isinstance(value, dict):
            _validate_no_forbidden_metadata_keys(value)
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    _validate_no_forbidden_metadata_keys(item)

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

_FORBIDDEN_KEYS = {
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
        validated_metadata = self._validate_metadata_json(metadata_json)
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
        self, metadata_json: dict[str, object] | None
    ) -> dict[str, object] | None:
        if metadata_json is None:
            return None
        self._validate_no_forbidden_metadata_keys(metadata_json)
        if self._calculate_json_depth(metadata_json) > 3:
            raise ValueError("Audit metadata exceeds max nesting depth")
        try:
            payload = json.dumps(metadata_json, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("Audit metadata contains unsupported value types") from exc
        if len(payload.encode("utf-8")) > 8192:
            raise ValueError("Audit metadata exceeds max size")
        return metadata_json

    def _calculate_json_depth(self, value: object) -> int:
        if isinstance(value, dict):
            return 1 + max(
                (self._calculate_json_depth(v) for v in value.values()), default=0
            )
        if isinstance(value, list):
            return 1 + max((self._calculate_json_depth(v) for v in value), default=0)
        if isinstance(value, (str, int, float, bool)) or value is None:
            return 0
        raise ValueError("Audit metadata contains unsupported value types")

    def _validate_no_forbidden_metadata_keys(
        self, metadata_json: dict[str, object]
    ) -> None:
        stack: list[object] = [metadata_json]
        while stack:
            current = stack.pop()
            if isinstance(current, dict):
                for key, val in current.items():
                    if key.lower() in _FORBIDDEN_KEYS:
                        raise ValueError("Audit metadata contains forbidden keys")
                    stack.append(val)
            elif isinstance(current, list):
                stack.extend(current)

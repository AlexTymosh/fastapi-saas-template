from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator

from app.memberships.models.membership import MembershipRole


class InviteOutboxPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    invite_id: UUID
    organisation_id: UUID | None = None
    email: EmailStr | None = None
    encrypted_raw_token: str
    purpose: Literal["created", "resent"] | None = None
    role: MembershipRole | None = None

    @field_validator("encrypted_raw_token")
    @classmethod
    def validate_encrypted_raw_token(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("encrypted_raw_token must not be blank")
        return value


def parse_invite_outbox_payload(
    payload: Mapping[str, object],
) -> InviteOutboxPayload:
    return InviteOutboxPayload.model_validate(payload)


__all__ = [
    "InviteOutboxPayload",
    "parse_invite_outbox_payload",
]

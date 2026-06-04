from __future__ import annotations

from uuid import UUID

from app.invites.models.invite import Invite

SCRUBBED_INVITE_EMAIL_DOMAIN = "anonymous.invalid"
SCRUBBED_INVITE_TOKEN_PREFIX = "scrubbed-invite"


def scrubbed_invite_email(invite_id: UUID) -> str:
    return f"deleted-invite-{invite_id}@{SCRUBBED_INVITE_EMAIL_DOMAIN}"


def scrubbed_invite_token_hash(invite_id: UUID) -> str:
    return f"{SCRUBBED_INVITE_TOKEN_PREFIX}:{invite_id}"


def is_scrubbed_invite(invite: Invite) -> bool:
    return invite.email.endswith(
        f"@{SCRUBBED_INVITE_EMAIL_DOMAIN}"
    ) and invite.token_hash.startswith(f"{SCRUBBED_INVITE_TOKEN_PREFIX}:")

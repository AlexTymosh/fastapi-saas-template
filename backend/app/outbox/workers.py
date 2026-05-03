from __future__ import annotations

from hashlib import sha256
from uuid import UUID

import dramatiq
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.core.tasks import configure_broker
from app.invites.models.invite import Invite, InviteStatus
from app.invites.services.delivery import get_invite_token_sink
from app.outbox.models.outbox_event import OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.services.payload_crypto import OutboxPayloadCrypto

log = get_logger(__name__)
configure_broker(require_redis=False)


class InviteOutboxPayload(BaseModel):
    invite_id: UUID
    organisation_id: UUID | None = None
    email: str | None = None
    encrypted_raw_token: str
    purpose: str | None = None
    role: str | None = None


async def _get_claimed_event_context(
    event_id: str,
) -> tuple[str, dict[str, object], Invite | None]:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_by_id(UUID(event_id))
            if event is None or event.status != OutboxStatus.PROCESSING.value:
                return "skip", {}, None
            if event.status in {
                OutboxStatus.PROCESSED.value,
                OutboxStatus.FAILED.value,
            }:
                return "skip", {}, None
            if event.event_type not in {
                OutboxEventType.INVITE_CREATED.value,
                OutboxEventType.INVITE_RESEND.value,
            }:
                return "mark_processed", {}, None
            try:
                payload = InviteOutboxPayload.model_validate(event.payload_json)
            except ValidationError:
                log.warning("outbox_payload_validation_failed", event_id=event_id)
                return "invalid_outbox_payload", {}, None
            invite = (
                await session.execute(
                    select(Invite).where(Invite.id == payload.invite_id)
                )
            ).scalar_one_or_none()
            if invite is None:
                return "invite_not_found", {}, None
            if invite.status != InviteStatus.PENDING:
                return "mark_processed", {}, None
            crypto = OutboxPayloadCrypto.from_settings(settings=get_settings())
            try:
                raw_token = crypto.decrypt_token(payload.encrypted_raw_token)
            except ValueError:
                log.warning("outbox_payload_decryption_failed", event_id=event_id)
                return "outbox_payload_decryption_failed", {}, None
            token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
            if token_hash != invite.token_hash:
                return "token_hash_mismatch", {}, None
            return "deliver", {"raw_token": raw_token}, invite


async def _apply_result(
    event_id: str, *, success: bool, error: str | None = None
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_by_id(UUID(event_id))
            if event is None or event.status != OutboxStatus.PROCESSING.value:
                return
            if success:
                await repository.mark_processed(event=event)
            elif error is not None:
                await repository.mark_failed_attempt(event=event, error=error)


async def _process_outbox_event(event_id: str) -> None:
    action, context, invite = await _get_claimed_event_context(event_id)
    if action == "skip":
        return
    if action == "mark_processed":
        await _apply_result(event_id, success=True)
        return
    if action in {
        "invite_not_found",
        "token_hash_mismatch",
        "outbox_payload_decryption_failed",
        "invalid_outbox_payload",
    }:
        await _apply_result(event_id, success=False, error=action)
        return

    try:
        sink = get_invite_token_sink()
        await sink.deliver(invite=invite, raw_token=str(context["raw_token"]))
    except Exception as exc:
        await _apply_result(
            event_id,
            success=False,
            error=f"delivery_failed:{type(exc).__name__}",
        )
        log.warning("outbox_delivery_failed", event_id=event_id)
        return

    await _apply_result(event_id, success=True)


@dramatiq.actor(max_retries=0)
async def process_outbox_event(event_id: str) -> None:
    await _process_outbox_event(event_id)

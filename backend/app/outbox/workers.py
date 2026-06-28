from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from secrets import token_urlsafe
from uuid import UUID

import dramatiq
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config.settings import get_settings
from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.core.tasks import configure_broker
from app.invites.models.invite import Invite, InviteStatus
from app.invites.repositories.invites import InviteRepository
from app.invites.services.delivery import get_invite_token_sink
from app.outbox.models.outbox_event import OutboxEventType, OutboxStatus
from app.outbox.repositories.outbox_events import OutboxEventRepository
from app.outbox.schemas.payloads import parse_invite_outbox_payload
from app.outbox.services.payload_crypto import OutboxPayloadCrypto

log = get_logger(__name__)
configure_broker(require_redis=False)


async def _get_claimed_event_context(
    event_id: str,
) -> tuple[str, dict[str, object], Invite | None]:
    session_factory = get_session_factory()
    delivery_claim_token = token_urlsafe(32)
    context: dict[str, object] = {"delivery_claim_token": delivery_claim_token}

    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.claim_processing_event_for_delivery(
                event_id=UUID(event_id),
                claim_token=delivery_claim_token,
            )
            if event is None:
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
                return "mark_processed", context, None
            try:
                payload = parse_invite_outbox_payload(event.payload_json)
            except (ValidationError, TypeError, ValueError):
                log.warning(
                    "malformed_outbox_payload",
                    event_id=event_id,
                    event_type=event.event_type,
                )
                return "malformed_outbox_payload", context, None
            invite = (
                await session.execute(
                    select(Invite).where(Invite.id == payload.invite_id)
                )
            ).scalar_one_or_none()
            if invite is None:
                return "invite_not_found", context, None
            if invite.status != InviteStatus.PENDING:
                return "mark_processed", context, None
            expired_invite = await InviteRepository(
                session
            ).mark_pending_invite_expired_by_id(
                invite_id=invite.id,
                organisation_id=invite.organisation_id,
                now=datetime.now(UTC),
            )
            if expired_invite is not None:
                return "mark_processed", context, None
            crypto = OutboxPayloadCrypto.from_settings(settings=get_settings())
            try:
                raw_token = crypto.decrypt_token(payload.encrypted_raw_token)
            except ValueError:
                log.warning("outbox_payload_decryption_failed", event_id=event_id)
                return "outbox_payload_decryption_failed", context, None
            token_hash = sha256(raw_token.encode("utf-8")).hexdigest()
            if token_hash != invite.token_hash:
                return "token_hash_mismatch", context, None
            context["raw_token"] = raw_token
            return "deliver", context, invite


async def _apply_result(
    event_id: str,
    *,
    delivery_claim_token: str,
    success: bool,
    error: str | None = None,
) -> None:
    session_factory = get_session_factory()
    async with session_factory() as session:
        async with session.begin():
            repository = OutboxEventRepository(session)
            event = await repository.get_delivery_claimed_event(
                event_id=UUID(event_id),
                claim_token=delivery_claim_token,
            )
            if event is None:
                return
            if success:
                await repository.mark_processed(event=event)
            elif error is not None:
                await repository.mark_failed_attempt(event=event, error=error)


def _delivery_claim_token(context: dict[str, object]) -> str:
    return str(context["delivery_claim_token"])


async def _process_outbox_event(event_id: str) -> None:
    action, context, invite = await _get_claimed_event_context(event_id)
    if action == "skip":
        return

    claim_token = _delivery_claim_token(context)
    if action == "mark_processed":
        await _apply_result(event_id, delivery_claim_token=claim_token, success=True)
        return
    if action in {
        "invite_not_found",
        "token_hash_mismatch",
        "outbox_payload_decryption_failed",
        "malformed_outbox_payload",
    }:
        await _apply_result(
            event_id,
            delivery_claim_token=claim_token,
            success=False,
            error=action,
        )
        return

    try:
        sink = get_invite_token_sink()
        await sink.deliver(invite=invite, raw_token=str(context["raw_token"]))
    except Exception as exc:
        await _apply_result(
            event_id,
            delivery_claim_token=claim_token,
            success=False,
            error=f"delivery_failed:{type(exc).__name__}",
        )
        log.warning("outbox_delivery_failed", event_id=event_id)
        return

    await _apply_result(event_id, delivery_claim_token=claim_token, success=True)


@dramatiq.actor(max_retries=0)
async def process_outbox_event(event_id: str) -> None:
    await _process_outbox_event(event_id)

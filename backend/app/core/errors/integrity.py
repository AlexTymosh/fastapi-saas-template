from __future__ import annotations

from sqlalchemy.exc import IntegrityError

from app.core.errors.exceptions import ConflictError


def raise_conflict_for_integrity_error(exc: IntegrityError) -> None:
    message = str(exc.orig).lower() if exc.orig is not None else str(exc).lower()

    if "external_auth_id" in message:
        raise ConflictError(detail="External auth id already exists") from exc

    if "organisations.slug" in message or "organisation_slug" in message:
        raise ConflictError(detail="Organisation slug already exists") from exc

    has_membership_unique_error = (
        "memberships.user_id, memberships.organisation_id" in message
        or (
            "user_id" in message
            and "organisation_id" in message
            and "membership" in message
        )
    )
    if has_membership_unique_error:
        raise ConflictError(detail="Membership already exists for this user") from exc

    raise ConflictError(detail="Resource already exists") from exc

from __future__ import annotations

from app.core.auth import AuthenticatedPrincipal
from app.core.errors.exceptions import ForbiddenError
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.users.models.user import User, UserStatus


def ensure_email_verified(identity: AuthenticatedPrincipal) -> None:
    if not identity.email_verified:
        raise ForbiddenError(detail="Email verification is required")


def ensure_user_active(user: User) -> None:
    if user.status == UserStatus.SUSPENDED:
        raise ForbiddenError(detail="User is suspended")


def ensure_organisation_active(organisation: Organisation) -> None:
    if organisation.status == OrganisationStatus.SUSPENDED:
        raise ForbiddenError(detail="Organisation is suspended")

from __future__ import annotations

from app.core.errors.exceptions import ForbiddenError
from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.users.models.user import User, UserStatus


def ensure_user_active(user: User) -> None:
    if user.status == UserStatus.SUSPENDED:
        raise ForbiddenError(detail="User is suspended")


def ensure_organisation_active(organisation: Organisation) -> None:
    if organisation.status == OrganisationStatus.SUSPENDED:
        raise ForbiddenError(detail="Organisation is suspended")

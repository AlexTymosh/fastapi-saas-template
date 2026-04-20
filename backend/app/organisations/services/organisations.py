from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ConflictError, NotFoundError
from app.organisations.models.organisation import Organisation
from app.organisations.repositories.organisations import OrganisationRepository

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class OrganisationService:
    def __init__(self, session: AsyncSession) -> None:
        self.organisation_repository = OrganisationRepository(session)

    @staticmethod
    def normalize_slug(raw_slug: str) -> str:
        normalized = raw_slug.strip().lower()
        if not normalized:
            raise ConflictError(detail="Organisation slug cannot be blank")
        if not _SLUG_PATTERN.fullmatch(normalized):
            raise ConflictError(
                detail=(
                    "Organisation slug may contain only lowercase letters, "
                    "digits, and hyphens"
                )
            )
        return normalized

    async def create_organisation(self, *, name: str, slug: str) -> Organisation:
        normalized_slug = self.normalize_slug(slug)
        existing = await self.organisation_repository.get_by_slug(normalized_slug)
        if existing is not None:
            raise ConflictError(detail="Organisation slug already exists")

        try:
            return await self.organisation_repository.create(
                name=name.strip(),
                slug=normalized_slug,
            )
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc

    async def get_organisation(self, organisation_id: UUID) -> Organisation:
        organisation = await self.organisation_repository.get_by_id(organisation_id)
        if organisation is None:
            raise NotFoundError(detail="Organisation not found")
        return organisation

from __future__ import annotations

from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import ConflictError, NotFoundError
from app.organisations.models.organisation import Organisation
from app.organisations.repositories.organisations import OrganisationRepository


class OrganisationService:
    def __init__(self, session: AsyncSession) -> None:
        self.organisation_repository = OrganisationRepository(session)

    async def create_organisation(self, *, name: str, slug: str) -> Organisation:
        existing = await self.organisation_repository.get_by_slug(slug)
        if existing is not None:
            raise ConflictError(detail="Organisation slug already exists")

        try:
            return await self.organisation_repository.create(name=name, slug=slug)
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc

    async def get_organisation(self, organisation_id: UUID) -> Organisation:
        organisation = await self.organisation_repository.get_by_id(organisation_id)
        if organisation is None:
            raise NotFoundError(detail="Organisation not found")
        return organisation

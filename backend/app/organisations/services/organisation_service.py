from __future__ import annotations

from uuid import UUID

from app.core.errors.exceptions import ConflictError, NotFoundError
from app.organisations.models.organisation import Organisation
from app.organisations.repositories.organisation_repository import (
    OrganisationRepository,
)


class OrganisationService:
    def __init__(self, organisation_repository: OrganisationRepository) -> None:
        self.organisation_repository = organisation_repository

    async def create(self, *, name: str, slug: str) -> Organisation:
        existing = await self.organisation_repository.get_by_slug(slug)
        if existing is not None:
            raise ConflictError(detail="Organisation slug already exists.")

        return await self.organisation_repository.create(name=name, slug=slug)

    async def get_by_id(self, organisation_id: UUID) -> Organisation:
        organisation = await self.organisation_repository.get_by_id(organisation_id)
        if organisation is None:
            raise NotFoundError(detail="Organisation not found.")
        return organisation

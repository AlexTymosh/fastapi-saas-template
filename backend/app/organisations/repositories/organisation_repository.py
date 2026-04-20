from __future__ import annotations

from uuid import UUID

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organisations.models.organisation import Organisation


class OrganisationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, slug: str) -> Organisation:
        organisation = Organisation(name=name, slug=slug)
        self.session.add(organisation)
        await self.session.flush()
        return organisation

    async def get_by_id(self, organisation_id: UUID) -> Organisation | None:
        stmt: Select[tuple[Organisation]] = select(Organisation).where(
            Organisation.id == organisation_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_slug(self, slug: str) -> Organisation | None:
        stmt: Select[tuple[Organisation]] = select(Organisation).where(
            Organisation.slug == slug
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

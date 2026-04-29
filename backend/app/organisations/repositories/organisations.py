from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organisations.models.organisation import Organisation


class OrganisationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, *, name: str, slug: str) -> Organisation:
        organisation = Organisation(name=name, slug=slug)
        self.session.add(organisation)
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

    async def get_by_slug(self, slug: str) -> Organisation | None:
        stmt = select(Organisation).where(
            Organisation.slug == slug,
            Organisation.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(self, organisation_id: UUID) -> Organisation | None:
        stmt = select(Organisation).where(
            Organisation.id == organisation_id,
            Organisation.deleted_at.is_(None),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_details(
        self,
        organisation: Organisation,
        *,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organisation:
        if name is not None:
            organisation.name = name
        if slug is not None:
            organisation.slug = slug
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

    async def update_slug(self, organisation: Organisation, slug: str) -> Organisation:
        return await self.update_details(organisation, slug=slug)

    async def soft_delete(self, organisation: Organisation) -> Organisation:
        organisation.slug = self._build_deleted_slug(
            organisation_id=organisation.id,
            slug=organisation.slug,
        )
        organisation.deleted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

    @staticmethod
    def _build_deleted_slug(*, organisation_id: UUID, slug: str) -> str:
        deleted_prefix = f"deleted-{organisation_id}-"
        max_slug_length = 255
        available_slug_length = max_slug_length - len(deleted_prefix)
        preserved_slug = slug[:available_slug_length]
        return f"{deleted_prefix}{preserved_slug}"

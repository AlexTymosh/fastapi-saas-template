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

    async def update_slug(self, organisation: Organisation, slug: str) -> Organisation:
        organisation.slug = slug
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

    async def soft_delete(self, organisation: Organisation) -> Organisation:
        organisation.slug = self._build_deleted_slug(organisation)
        organisation.deleted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

    @staticmethod
    def _build_deleted_slug(organisation: Organisation) -> str:
        prefix = f"deleted-{organisation.id}-"
        max_slug_length = 255
        max_suffix_length = max_slug_length - len(prefix)
        preserved_suffix = organisation.slug[: max(0, max_suffix_length)]
        return f"{prefix}{preserved_suffix}"

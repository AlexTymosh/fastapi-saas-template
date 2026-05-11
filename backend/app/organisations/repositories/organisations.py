from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.organisations.models.organisation import Organisation, OrganisationStatus


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

    async def get_by_id(
        self,
        organisation_id: UUID,
        *,
        include_deleted: bool = False,
    ) -> Organisation | None:
        stmt = select(Organisation).where(Organisation.id == organisation_id)
        if not include_deleted:
            stmt = stmt.where(Organisation.deleted_at.is_(None))
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_paginated(
        self,
        *,
        limit: int,
        offset: int,
        include_deleted: bool = False,
        status: OrganisationStatus | None = None,
        q: str | None = None,
    ) -> tuple[list[Organisation], int]:
        stmt = select(Organisation)
        total_stmt = select(func.count()).select_from(Organisation)
        conditions = []
        if not include_deleted:
            conditions.append(Organisation.deleted_at.is_(None))
        if status is not None:
            conditions.append(Organisation.status == status)
        if q:
            pattern = f"%{q.lower()}%"
            conditions.append(
                or_(
                    func.lower(Organisation.name).like(pattern),
                    func.lower(Organisation.slug).like(pattern),
                )
            )
        for condition in conditions:
            stmt = stmt.where(condition)
            total_stmt = total_stmt.where(condition)
        stmt = (
            stmt.order_by(Organisation.created_at.desc(), Organisation.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        total_result = await self.session.execute(total_stmt)
        return list(result.scalars().all()), int(total_result.scalar_one())

    async def list_limited_paginated(
        self,
        *,
        limit: int,
        offset: int,
        status: OrganisationStatus | None = None,
        q: str | None = None,
    ) -> tuple[list[Organisation], int]:
        stmt = select(Organisation).where(Organisation.deleted_at.is_(None))
        total_stmt = (
            select(func.count())
            .select_from(Organisation)
            .where(Organisation.deleted_at.is_(None))
        )
        conditions = []
        if status is not None:
            conditions.append(Organisation.status == status)
        if q:
            pattern = f"%{q.lower()}%"
            conditions.append(
                or_(
                    func.lower(Organisation.name).like(pattern),
                    func.lower(Organisation.slug).like(pattern),
                )
            )
        for condition in conditions:
            stmt = stmt.where(condition)
            total_stmt = total_stmt.where(condition)
        stmt = (
            stmt.order_by(Organisation.created_at.desc(), Organisation.id.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        total_result = await self.session.execute(total_stmt)
        return list(result.scalars().all()), int(total_result.scalar_one())

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

    async def set_status(
        self,
        organisation: Organisation,
        *,
        status: OrganisationStatus,
        suspended_at: datetime | None,
        suspended_reason: str | None,
    ) -> Organisation:
        organisation.status = status
        organisation.suspended_at = suspended_at
        organisation.suspended_reason = suspended_reason
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

    async def soft_delete(self, organisation: Organisation) -> Organisation:
        organisation.deleted_at = datetime.now(UTC)
        await self.session.flush()
        await self.session.refresh(organisation)
        return organisation

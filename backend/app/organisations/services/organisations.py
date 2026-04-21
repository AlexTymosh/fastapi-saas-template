from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors.exceptions import BadRequestError, ConflictError, ForbiddenError, NotFoundError
from app.memberships.models.membership import MembershipRole
from app.memberships.services.memberships import MembershipService
from app.organisations.models.organisation import Organisation
from app.organisations.repositories.organisations import OrganisationRepository

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class OrganisationService:
    def __init__(self, session: AsyncSession) -> None:
        self.organisation_repository = OrganisationRepository(session)
        self.membership_service = MembershipService(session)

    @staticmethod
    def normalize_name(raw_name: str) -> str:
        normalized = raw_name.strip()
        if not normalized:
            raise BadRequestError(detail="Organisation name cannot be blank")
        return normalized

    @staticmethod
    def normalize_slug(raw_slug: str) -> str:
        normalized = raw_slug.strip().lower()
        if not normalized:
            raise BadRequestError(detail="Organisation slug cannot be blank")
        if not _SLUG_PATTERN.fullmatch(normalized):
            raise BadRequestError(
                detail=(
                    "Organisation slug may contain only lowercase letters, "
                    "digits, and hyphens"
                )
            )
        return normalized

    async def create_organisation(self, *, name: str, slug: str) -> Organisation:
        normalized_name = self.normalize_name(name)
        normalized_slug = self.normalize_slug(slug)
        existing = await self.organisation_repository.get_by_slug(normalized_slug)
        if existing is not None:
            raise ConflictError(detail="Organisation slug already exists")

        try:
            return await self.organisation_repository.create(
                name=normalized_name,
                slug=normalized_slug,
            )
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc

    async def get_organisation(self, organisation_id: UUID) -> Organisation:
        organisation = await self.organisation_repository.get_by_id(organisation_id)
        if organisation is None:
            raise NotFoundError(detail="Organisation not found")
        return organisation

    async def update_slug(
        self,
        *,
        organisation_id: UUID,
        actor_role: MembershipRole,
        slug: str,
    ) -> Organisation:
        if actor_role not in {MembershipRole.OWNER, MembershipRole.ADMIN}:
            raise ForbiddenError(detail="Only owner or admin can update organisation slug")

        organisation = await self.get_organisation(organisation_id)
        normalized_slug = self.normalize_slug(slug)
        return await self.organisation_repository.update_slug(organisation, slug=normalized_slug)

    async def soft_delete_organisation(
        self,
        *,
        organisation_id: UUID,
        actor_role: MembershipRole,
    ) -> Organisation:
        if actor_role != MembershipRole.OWNER:
            raise ForbiddenError(detail="Only owner can delete organisation")

        organisation = await self.get_organisation(organisation_id)
        owner_count = await self.membership_service.membership_repository.count_active_owners(
            organisation_id=organisation_id
        )
        if owner_count < 1:
            raise ConflictError(detail="Organisation must have at least one owner")

        await self.membership_service.membership_repository.deactivate_all_for_organisation(
            organisation_id=organisation_id
        )
        return await self.organisation_repository.soft_delete(organisation)

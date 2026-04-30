from __future__ import annotations

import re
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.access_control.guards import ensure_organisation_active
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
)
from app.memberships.models.membership import MembershipRole
from app.memberships.repositories.memberships import MembershipRepository
from app.organisations.models.organisation import Organisation
from app.organisations.repositories.organisations import OrganisationRepository
from app.users.services.users import UserService

_SLUG_PATTERN = re.compile(r"^[a-z0-9-]+$")


class OrganisationService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.organisation_repository = OrganisationRepository(session)
        self.membership_repository = MembershipRepository(session)
        self.user_service = UserService(session)
        self.audit_event_service = AuditEventService(session)

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
        if self.session.in_transaction():
            return await self._create_organisation(name=name, slug=slug)
        async with self.session.begin():
            return await self._create_organisation(name=name, slug=slug)

    async def _create_organisation(self, *, name: str, slug: str) -> Organisation:
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

    async def update_organisation_details(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organisation:
        if self.session.in_transaction():
            return await self._update_organisation_details(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                name=name,
                slug=slug,
            )
        async with self.session.begin():
            return await self._update_organisation_details(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
                name=name,
                slug=slug,
            )

    async def _update_organisation_details(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
        name: str | None = None,
        slug: str | None = None,
    ) -> Organisation:
        organisation = await self.get_organisation(organisation_id)
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        ensure_organisation_active(organisation)
        membership = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        allowed_roles = {MembershipRole.OWNER, MembershipRole.ADMIN}
        if membership is None or membership.role not in allowed_roles:
            raise ForbiddenError(
                detail="You are not allowed to update organisation details"
            )

        normalized_name = self.normalize_name(name) if name is not None else None
        normalized_slug = self.normalize_slug(slug) if slug is not None else None
        changed_fields: list[str] = []
        if normalized_name is not None and normalized_name != organisation.name:
            changed_fields.append("name")
        if normalized_slug is not None and normalized_slug != organisation.slug:
            changed_fields.append("slug")
        previous_slug = organisation.slug
        try:
            updated = await self.organisation_repository.update_details(
                organisation,
                name=normalized_name,
                slug=normalized_slug,
            )
            if changed_fields:
                metadata_json: dict[str, object] = {"changed_fields": changed_fields}
                if "slug" in changed_fields:
                    metadata_json["old_slug"] = previous_slug
                    metadata_json["new_slug"] = updated.slug
                await self.audit_event_service.record_event(
                    actor_user_id=actor_user_id,
                    category=AuditCategory.TENANT,
                    action=AuditAction.ORGANISATION_UPDATED,
                    target_type=AuditTargetType.ORGANISATION.value,
                    target_id=updated.id,
                    metadata_json=metadata_json,
                )
            return updated
        except IntegrityError as exc:
            raise ConflictError(detail="Organisation slug already exists") from exc

    async def soft_delete(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
    ) -> Organisation:
        if self.session.in_transaction():
            return await self._soft_delete(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
            )
        async with self.session.begin():
            return await self._soft_delete(
                organisation_id=organisation_id,
                actor_user_id=actor_user_id,
            )

    async def _soft_delete(
        self,
        *,
        organisation_id: UUID,
        actor_user_id: UUID,
    ) -> Organisation:
        organisation = await self.get_organisation(organisation_id)
        actor_user = await self.user_service.get_user_by_id(actor_user_id)
        await self.user_service.ensure_user_is_active(actor_user)
        ensure_organisation_active(organisation)
        membership = await self.membership_repository.get_membership(
            user_id=actor_user_id,
            organisation_id=organisation_id,
        )
        if membership is None or membership.role != MembershipRole.OWNER:
            raise ForbiddenError(detail="Only owner can delete organisation")

        owner_count = await self.membership_repository.count_active_owners(
            organisation_id=organisation_id
        )
        if owner_count < 1:
            raise ConflictError(
                detail="Organisation must always have at least one owner"
            )

        await self.membership_repository.deactivate_organisation_memberships(
            organisation_id=organisation_id
        )
        previous_slug = organisation.slug
        deleted = await self.organisation_repository.soft_delete(organisation)
        await self.audit_event_service.record_event(
            actor_user_id=actor_user_id,
            category=AuditCategory.TENANT,
            action=AuditAction.ORGANISATION_DELETED,
            target_type=AuditTargetType.ORGANISATION.value,
            target_id=deleted.id,
            metadata_json={
                "previous_slug": previous_slug,
                "deleted_slug": deleted.slug,
                "soft_delete": True,
            },
        )
        return deleted

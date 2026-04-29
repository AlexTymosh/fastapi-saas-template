from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.memberships.schemas.memberships import (
    DirectoryCollectionMeta,
    DirectoryCollectionResponse,
    DirectoryItemResponse,
    MembershipCollectionMeta,
    MembershipCollectionResponse,
    MembershipResponse,
    UpdateMembershipRoleRequest,
)
from app.organisations.schemas.organisations import (
    CreateOrganisationRequest,
    OrganisationResponse,
    UpdateOrganisationRequest,
    UpdateOrganisationSlugRequest,
)
from app.organisations.services.access import OrganisationAccessService
from app.organisations.services.onboarding import OnboardingService
from app.organisations.services.organisations import OrganisationService
from app.users.services.users import UserService

router = APIRouter(prefix="/organisations", tags=["organisations"])

DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]
PrincipalDep = Annotated[
    AuthenticatedPrincipal,
    Depends(require_authenticated_principal),
]


@router.post(
    "",
    response_model=OrganisationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERROR_RESPONSES,
    name="create_organisation",
)
async def create_organisation(
    payload: CreateOrganisationRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> OrganisationResponse:
    onboarding_service = OnboardingService(db_session)
    _, organisation, _ = await onboarding_service.create_organisation_for_current_user(
        identity=identity,
        organisation_name=payload.name,
        organisation_slug=payload.slug,
    )
    return OrganisationResponse.model_validate(organisation)


@router.get(
    "/{organisation_id}",
    response_model=OrganisationResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="get_organisation",
)
async def get_organisation(
    organisation_id: UUID,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> OrganisationResponse:
    access_service = OrganisationAccessService(db_session)
    organisation = await access_service.get_organisation_for_member(
        identity=identity,
        organisation_id=organisation_id,
    )
    return OrganisationResponse.model_validate(organisation)


@router.patch(
    "/{organisation_id}/slug",
    response_model=OrganisationResponse,
    responses=WRITE_ERROR_RESPONSES,
    name="update_organisation_slug",
)
async def update_organisation_slug(
    organisation_id: UUID,
    payload: UpdateOrganisationSlugRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> OrganisationResponse:
    user = await UserService(db_session).provision_current_user(identity)
    service = OrganisationService(db_session)
    organisation = await service.update_slug(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        slug=payload.slug,
    )
    return OrganisationResponse.model_validate(organisation)


@router.patch(
    "/{organisation_id}",
    response_model=OrganisationResponse,
    responses=WRITE_ERROR_RESPONSES,
    name="update_organisation",
)
async def update_organisation(
    organisation_id: UUID,
    payload: UpdateOrganisationRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> OrganisationResponse:
    user = await UserService(db_session).provision_current_user(identity)
    service = OrganisationService(db_session)
    organisation = await service.update_organisation_details(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        name=payload.name,
        slug=payload.slug,
    )
    return OrganisationResponse.model_validate(organisation)


@router.delete(
    "/{organisation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERROR_RESPONSES,
    name="delete_organisation",
)
async def delete_organisation(
    organisation_id: UUID,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> None:
    user = await UserService(db_session).provision_current_user(identity)
    service = OrganisationService(db_session)
    await service.soft_delete(organisation_id=organisation_id, actor_user_id=user.id)


@router.get(
    "/{organisation_id}/memberships",
    response_model=MembershipCollectionResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="list_organisation_memberships",
)
async def list_organisation_memberships(
    organisation_id: UUID,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> MembershipCollectionResponse:
    access_service = OrganisationAccessService(db_session)
    memberships = await access_service.list_memberships_for_member_organisation(
        identity=identity,
        organisation_id=organisation_id,
    )

    return MembershipCollectionResponse(
        data=[MembershipResponse.model_validate(item) for item in memberships],
        meta=MembershipCollectionMeta(total=len(memberships)),
        links={},
    )


@router.get(
    "/{organisation_id}/directory",
    response_model=DirectoryCollectionResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="list_organisation_directory",
)
async def list_organisation_directory(
    organisation_id: UUID,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> DirectoryCollectionResponse:
    access_service = OrganisationAccessService(db_session)
    memberships = await access_service.list_directory_for_member_organisation(
        identity=identity,
        organisation_id=organisation_id,
    )
    return DirectoryCollectionResponse(
        data=[
            DirectoryItemResponse(
                display_name=(
                    f"{item.user.first_name} {item.user.last_name}".strip()
                    if item.user.first_name or item.user.last_name
                    else "Organisation member"
                ),
                role_label="Member",
            )
            for item in memberships
        ],
        meta=DirectoryCollectionMeta(total=len(memberships)),
        links={},
    )


@router.patch(
    "/{organisation_id}/memberships/{membership_id}/role",
    response_model=MembershipResponse,
    responses=WRITE_ERROR_RESPONSES,
    name="change_membership_role",
)
async def change_membership_role(
    organisation_id: UUID,
    membership_id: UUID,
    payload: UpdateMembershipRoleRequest,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> MembershipResponse:
    user = await UserService(db_session).provision_current_user(identity)
    await OrganisationAccessService(db_session).ensure_write_access(
        identity=identity,
        organisation_id=organisation_id,
    )
    membership = await OrganisationAccessService(
        db_session
    ).membership_service.change_membership_role(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        membership_id=membership_id,
        role=payload.role,
    )
    return MembershipResponse.model_validate(membership)


@router.delete(
    "/{organisation_id}/memberships/{membership_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERROR_RESPONSES,
    name="remove_membership",
)
async def remove_membership(
    organisation_id: UUID,
    membership_id: UUID,
    identity: PrincipalDep,
    db_session: DbSessionDep,
) -> None:
    user = await UserService(db_session).provision_current_user(identity)
    await OrganisationAccessService(db_session).ensure_write_access(
        identity=identity,
        organisation_id=organisation_id,
    )
    await OrganisationAccessService(db_session).membership_service.remove_membership(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        membership_id=membership_id,
    )

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.memberships.schemas.memberships import (
    MembershipCollectionMeta,
    MembershipCollectionResponse,
    MembershipResponse,
    UpdateMembershipRoleRequest,
)
from app.memberships.services.memberships import MembershipService
from app.organisations.schemas.organisations import (
    CreateOrganisationRequest,
    OrganisationDirectoryItemResponse,
    OrganisationDirectoryMeta,
    OrganisationDirectoryResponse,
    OrganisationResponse,
    UpdateOrganisationRequest,
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
    payload: CreateOrganisationRequest, identity: PrincipalDep, db_session: DbSessionDep
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
    organisation_id: UUID, identity: PrincipalDep, db_session: DbSessionDep
) -> OrganisationResponse:
    access_service = OrganisationAccessService(db_session)
    organisation = await access_service.get_organisation_for_member(
        identity=identity, organisation_id=organisation_id
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
    request: Request,
    db_session: DbSessionDep,
) -> OrganisationResponse:
    user = await UserService(db_session).provision_current_user(identity)
    service = OrganisationService(db_session)
    organisation = await service.update_organisation_details(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=user.id, request=request
        ),
        name=payload.name,
        slug=payload.slug,
    )
    return OrganisationResponse.model_validate(organisation)


@router.get(
    "/{organisation_id}/directory",
    response_model=OrganisationDirectoryResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="get_organisation_directory",
)
async def get_organisation_directory(
    organisation_id: UUID, identity: PrincipalDep, db_session: DbSessionDep
) -> OrganisationDirectoryResponse:
    user = await UserService(db_session).provision_current_user(identity)
    directory_members = await MembershipService(
        db_session
    ).list_directory_members_for_user(
        organisation_id=organisation_id,
        actor_user_id=user.id,
    )
    data = [
        OrganisationDirectoryItemResponse(
            display_name=item.display_name,
            role_label=item.role_label,
        )
        for item in directory_members
    ]
    return OrganisationDirectoryResponse(
        data=data, meta=OrganisationDirectoryMeta(total=len(data)), links={}
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
    request: Request,
    db_session: DbSessionDep,
) -> MembershipResponse:
    user = await UserService(db_session).provision_current_user(identity)
    membership = await MembershipService(db_session).change_membership_role(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=user.id, request=request
        ),
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
    request: Request,
    db_session: DbSessionDep,
) -> None:
    user = await UserService(db_session).provision_current_user(identity)
    await MembershipService(db_session).remove_membership(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=user.id, request=request
        ),
        membership_id=membership_id,
    )
    return None


@router.delete(
    "/{organisation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=WRITE_ERROR_RESPONSES,
    name="delete_organisation",
)
async def delete_organisation(
    organisation_id: UUID,
    identity: PrincipalDep,
    request: Request,
    db_session: DbSessionDep,
) -> None:
    user = await UserService(db_session).provision_current_user(identity)
    service = OrganisationService(db_session)
    await service.soft_delete(
        organisation_id=organisation_id,
        actor_user_id=user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=user.id, request=request
        ),
    )


@router.get(
    "/{organisation_id}/memberships",
    response_model=MembershipCollectionResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="list_organisation_memberships",
)
async def list_organisation_memberships(
    organisation_id: UUID, identity: PrincipalDep, db_session: DbSessionDep
) -> MembershipCollectionResponse:
    user = await UserService(db_session).provision_current_user(identity)
    memberships = await MembershipService(db_session).list_memberships_for_management(
        organisation_id=organisation_id,
        actor_user_id=user.id,
    )

    return MembershipCollectionResponse(
        data=[MembershipResponse.model_validate(item) for item in memberships],
        meta=MembershipCollectionMeta(total=len(memberships)),
        links={},
    )

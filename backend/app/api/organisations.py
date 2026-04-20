from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedIdentity, get_current_identity
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.schemas.organisations import (
    CreateOrganisationRequest,
    MembershipListResponse,
    MembershipResponse,
    OrganisationResponse,
)
from app.services.memberships import MembershipService
from app.services.onboarding import OnboardingService
from app.services.organisations import OrganisationService
from app.services.users import UserService

router = APIRouter(prefix="/organisations", tags=["organisations"])

CurrentIdentityDep = Annotated[AuthenticatedIdentity, Depends(get_current_identity)]
DbSessionDep = Annotated[AsyncSession, Depends(get_db_session)]


@router.post(
    "",
    response_model=OrganisationResponse,
    status_code=status.HTTP_201_CREATED,
    responses=WRITE_ERROR_RESPONSES,
    name="create_organisation",
)
async def create_organisation(
    payload: CreateOrganisationRequest,
    identity: CurrentIdentityDep,
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
    identity: CurrentIdentityDep,
    db_session: DbSessionDep,
) -> OrganisationResponse:
    user_service = UserService(db_session)
    organisation_service = OrganisationService(db_session)
    membership_service = MembershipService(db_session)

    user = await user_service.get_or_create_current_user(identity)
    await membership_service.ensure_user_has_membership(
        user_id=user.id,
        organisation_id=organisation_id,
    )
    organisation = await organisation_service.get_organisation(organisation_id)
    return OrganisationResponse.model_validate(organisation)


@router.get(
    "/{organisation_id}/memberships",
    response_model=MembershipListResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="list_organisation_memberships",
)
async def list_organisation_memberships(
    organisation_id: UUID,
    identity: CurrentIdentityDep,
    db_session: DbSessionDep,
) -> MembershipListResponse:
    user_service = UserService(db_session)
    organisation_service = OrganisationService(db_session)
    membership_service = MembershipService(db_session)

    user = await user_service.get_or_create_current_user(identity)
    await membership_service.ensure_user_has_membership(
        user_id=user.id,
        organisation_id=organisation_id,
    )
    await organisation_service.get_organisation(organisation_id)
    memberships = await membership_service.list_memberships_for_organisation(
        organisation_id,
    )

    return MembershipListResponse(
        data=[MembershipResponse.model_validate(item) for item in memberships]
    )

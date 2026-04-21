from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.organisations.schemas.organisations import (
    CreateOrganisationRequest,
    MembershipListResponse,
    MembershipResponse,
    OrganisationResponse,
)
from app.organisations.services.access import OrganisationAccessService
from app.organisations.services.onboarding import OnboardingService

router = APIRouter(prefix="/organisations", tags=["organisations"])

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
    identity: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_principal),
    ],
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
    identity: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_principal),
    ],
    db_session: DbSessionDep,
) -> OrganisationResponse:
    access_service = OrganisationAccessService(db_session)
    organisation = await access_service.get_organisation_for_member(
        identity=identity,
        organisation_id=organisation_id,
    )
    return OrganisationResponse.model_validate(organisation)


@router.get(
    "/{organisation_id}/memberships",
    response_model=MembershipListResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="list_organisation_memberships",
)
async def list_organisation_memberships(
    organisation_id: UUID,
    identity: Annotated[
        AuthenticatedPrincipal,
        Depends(require_authenticated_principal),
    ],
    db_session: DbSessionDep,
) -> MembershipListResponse:
    access_service = OrganisationAccessService(db_session)
    memberships = await access_service.list_memberships_for_member_organisation(
        identity=identity,
        organisation_id=organisation_id,
    )

    return MembershipListResponse(
        data=[MembershipResponse.model_validate(item) for item in memberships]
    )

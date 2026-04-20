from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from app.api.dependencies.domain_services import (
    get_membership_service,
    get_onboarding_service,
    get_organisation_service,
)
from app.core.auth import (
    AuthenticatedIdentity,
    get_current_authenticated_identity,
)
from app.core.errors.openapi import COMMON_ERROR_RESPONSES, WRITE_ERROR_RESPONSES
from app.memberships.schemas.membership import (
    MembershipListResponse,
    MembershipResponse,
)
from app.memberships.services.membership_service import MembershipService
from app.onboarding.services.onboarding_service import OnboardingService
from app.organisations.schemas.organisation import (
    OrganisationCreateRequest,
    OrganisationResponse,
)
from app.organisations.services.organisation_service import OrganisationService

router = APIRouter(tags=["organisations"])


@router.post(
    "/organisations",
    response_model=OrganisationResponse,
    responses=WRITE_ERROR_RESPONSES,
    name="organisations_create",
)
async def create_organisation(
    payload: OrganisationCreateRequest,
    identity: Annotated[
        AuthenticatedIdentity,
        Depends(get_current_authenticated_identity),
    ],
    onboarding_service: Annotated[OnboardingService, Depends(get_onboarding_service)],
) -> OrganisationResponse:
    organisation = await onboarding_service.create_organisation_for_current_user(
        identity=identity,
        name=payload.name,
        slug=payload.slug,
    )
    return OrganisationResponse.model_validate(organisation)


@router.get(
    "/organisations/{organisation_id}",
    response_model=OrganisationResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="organisations_get_by_id",
)
async def get_organisation_by_id(
    organisation_id: UUID,
    _: Annotated[AuthenticatedIdentity, Depends(get_current_authenticated_identity)],
    organisation_service: Annotated[
        OrganisationService,
        Depends(get_organisation_service),
    ],
) -> OrganisationResponse:
    organisation = await organisation_service.get_by_id(organisation_id)
    return OrganisationResponse.model_validate(organisation)


@router.get(
    "/organisations/{organisation_id}/memberships",
    response_model=MembershipListResponse,
    responses=COMMON_ERROR_RESPONSES,
    name="organisations_memberships_list",
)
async def list_organisation_memberships(
    organisation_id: UUID,
    _: Annotated[AuthenticatedIdentity, Depends(get_current_authenticated_identity)],
    membership_service: Annotated[
        MembershipService,
        Depends(get_membership_service),
    ],
) -> MembershipListResponse:
    memberships = await membership_service.list_memberships_for_organisation(
        organisation_id
    )
    return MembershipListResponse(
        data=[MembershipResponse.model_validate(item) for item in memberships]
    )

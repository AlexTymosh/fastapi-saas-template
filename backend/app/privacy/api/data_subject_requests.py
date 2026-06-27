from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.auth import AuthenticatedPrincipal, require_authenticated_principal
from app.core.db import get_db_session
from app.core.errors.openapi import (
    COMMON_ERROR_RESPONSES,
    RATE_LIMIT_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from app.core.rate_limit import (
    PRIVACY_DSR_SUBMIT_POLICY,
    TENANT_READ_POLICY,
    rate_limit_dependency,
)
from app.privacy.models.data_subject_request import (
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.schemas.data_subject_requests import (
    CreateDataSubjectRequest,
    DataSubjectRequestResponse,
    DataSubjectRequestsCollectionResponse,
    DataSubjectRequestsMeta,
)
from app.privacy.services.data_subject_requests import DataSubjectRequestService
from app.users.services.users import UserService

router = APIRouter(prefix="/privacy/data-subject-requests", tags=["privacy"])


@router.post(
    "",
    response_model=DataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def submit_data_subject_request(
    payload: CreateDataSubjectRequest,
    request: Request,
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[
        None, Depends(rate_limit_dependency(PRIVACY_DSR_SUBMIT_POLICY))
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> DataSubjectRequestResponse:
    async with db_session.begin():
        user = await UserService(db_session).get_current_user_by_external_auth_id(
            identity
        )
        dsr = await DataSubjectRequestService(db_session).submit_request(
            requester_user_id=user.id,
            request_type=payload.request_type.value,
            requester_note=payload.requester_note,
            idempotency_key=idempotency_key,
            audit_context=build_audit_context_from_request(
                actor_user_id=user.id, request=request
            ),
        )
    return DataSubjectRequestResponse.model_validate(dsr)


@router.get(
    "",
    response_model=DataSubjectRequestsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_own_data_subject_requests(
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(TENANT_READ_POLICY))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: DataSubjectRequestStatus | None = None,
    request_type: DataSubjectRequestType | None = None,
) -> DataSubjectRequestsCollectionResponse:
    user = await UserService(db_session).get_current_user_by_external_auth_id(identity)
    rows, total = await DataSubjectRequestService(db_session).list_own_requests(
        requester_user_id=user.id,
        limit=limit,
        offset=offset,
        status=status.value if status else None,
        request_type=request_type.value if request_type else None,
    )
    return DataSubjectRequestsCollectionResponse(
        data=[DataSubjectRequestResponse.model_validate(row) for row in rows],
        meta=DataSubjectRequestsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "/{request_id}",
    response_model=DataSubjectRequestResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_own_data_subject_request(
    request_id: UUID,
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(TENANT_READ_POLICY))],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DataSubjectRequestResponse:
    user = await UserService(db_session).get_current_user_by_external_auth_id(identity)
    row = await DataSubjectRequestService(db_session).get_own_request(
        requester_user_id=user.id, request_id=request_id
    )
    return DataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/cancel",
    response_model=DataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def cancel_own_data_subject_request(
    request_id: UUID,
    request: Request,
    identity: Annotated[
        AuthenticatedPrincipal, Depends(require_authenticated_principal)
    ],
    _rate_limit: Annotated[
        None, Depends(rate_limit_dependency(PRIVACY_DSR_SUBMIT_POLICY))
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DataSubjectRequestResponse:
    async with db_session.begin():
        user = await UserService(db_session).get_current_user_by_external_auth_id(
            identity
        )
        row = await DataSubjectRequestService(db_session).cancel_own_request(
            requester_user_id=user.id,
            request_id=request_id,
            audit_context=build_audit_context_from_request(
                actor_user_id=user.id, request=request
            ),
        )
    return DataSubjectRequestResponse.model_validate(row)

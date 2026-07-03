from __future__ import annotations

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from app.audit.context import build_audit_context_from_request
from app.core.db import get_db_session
from app.core.errors.openapi import (
    COMMON_ERROR_RESPONSES,
    RATE_LIMIT_ERROR_RESPONSES,
    WRITE_ERROR_RESPONSES,
)
from app.core.platform import (
    PlatformPermission,
    PlatformWriteContext,
    require_platform_permission,
    require_rate_limited_platform_write_context,
)
from app.core.rate_limit import PLATFORM_READ_POLICY, rate_limit_dependency
from app.privacy.models.data_subject_request import (
    DataSubjectRequestRepresentativeStatus,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.schemas.data_subject_requests import (
    ApproveDataSubjectRequest,
    CancelDataSubjectRequest,
    ExecuteErasureDataSubjectRequest,
    FulfilDataSubjectRequest,
    PlatformDataSubjectRequestResponse,
    PlatformDataSubjectRequestsCollectionResponse,
    PlatformDataSubjectRequestsMeta,
    RejectDataSubjectRequest,
    RejectRepresentativeAuthority,
    ReviewDataSubjectRequest,
    VerifyRepresentativeAuthority,
)
from app.privacy.services.data_subject_requests import DataSubjectRequestService

router = APIRouter(
    prefix="/platform/privacy/data-subject-requests", tags=["platform-privacy"]
)


@router.get(
    "",
    response_model=PlatformDataSubjectRequestsCollectionResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def list_platform_data_subject_requests(
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.PRIVACY_REQUESTS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status: DataSubjectRequestStatus | None = None,
    request_type: DataSubjectRequestType | None = None,
    subject_user_id: UUID | None = None,
    requester_user_id: UUID | None = None,
    due_before: datetime | None = None,
    due_after: datetime | None = None,
    representative_status: DataSubjectRequestRepresentativeStatus | None = None,
) -> PlatformDataSubjectRequestsCollectionResponse:
    rows, total = await DataSubjectRequestService(db_session).list_platform_requests(
        limit=limit,
        offset=offset,
        status=status.value if status else None,
        request_type=request_type.value if request_type else None,
        subject_user_id=subject_user_id,
        requester_user_id=requester_user_id,
        due_before=due_before,
        due_after=due_after,
        representative_status=(
            representative_status.value if representative_status else None
        ),
    )
    return PlatformDataSubjectRequestsCollectionResponse(
        data=[PlatformDataSubjectRequestResponse.model_validate(r) for r in rows],
        meta=PlatformDataSubjectRequestsMeta(total=total, limit=limit, offset=offset),
        links={},
    )


@router.get(
    "/{request_id}",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**COMMON_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def get_platform_data_subject_request(
    request_id: UUID,
    _rate_limit: Annotated[None, Depends(rate_limit_dependency(PLATFORM_READ_POLICY))],
    _: Annotated[
        object,
        Depends(require_platform_permission(PlatformPermission.PRIVACY_REQUESTS_READ)),
    ],
    db_session: Annotated[AsyncSession, Depends(get_db_session)],
) -> PlatformDataSubjectRequestResponse:
    row = await DataSubjectRequestService(db_session).get_platform_request(
        request_id=request_id
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/representative/verify",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def verify_platform_dsr_representative_authority(
    request_id: UUID,
    payload: VerifyRepresentativeAuthority,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(
        write_context.session
    ).verify_representative_authority(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        reason_code=payload.reason_code.value if payload.reason_code else None,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/representative/reject",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def reject_platform_dsr_representative_authority(
    request_id: UUID,
    payload: RejectRepresentativeAuthority,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(
        write_context.session
    ).reject_representative_authority(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        reason_code=payload.reason_code.value,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/review",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def review_platform_data_subject_request(
    request_id: UUID,
    _: ReviewDataSubjectRequest,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(write_context.session).mark_under_review(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/approve",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def approve_platform_data_subject_request(
    request_id: UUID,
    payload: ApproveDataSubjectRequest,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(write_context.session).approve_request(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        reason_code=payload.reason_code.value if payload.reason_code else None,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/reject",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def reject_platform_data_subject_request(
    request_id: UUID,
    payload: RejectDataSubjectRequest,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(write_context.session).reject_request(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        reason_code=payload.reason_code.value,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/cancel",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def cancel_platform_data_subject_request(
    request_id: UUID,
    _: CancelDataSubjectRequest,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(
        write_context.session
    ).cancel_platform_request(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/execute-erasure",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def execute_platform_data_subject_request_erasure(
    request_id: UUID,
    _: ExecuteErasureDataSubjectRequest,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_EXECUTE_ERASURE
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(
        write_context.session
    ).execute_approved_erasure_request_by_platform_staff(
        request_id=request_id,
        executor_user_id=actor.user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)


@router.post(
    "/{request_id}/fulfil",
    response_model=PlatformDataSubjectRequestResponse,
    responses={**WRITE_ERROR_RESPONSES, **RATE_LIMIT_ERROR_RESPONSES},
)
async def fulfil_platform_data_subject_request(
    request_id: UUID,
    _: FulfilDataSubjectRequest,
    request: Request,
    write_context: Annotated[
        PlatformWriteContext,
        Depends(
            require_rate_limited_platform_write_context(
                PlatformPermission.PRIVACY_REQUESTS_REVIEW
            ),
            scope="function",
        ),
    ],
) -> PlatformDataSubjectRequestResponse:
    actor = write_context.actor
    row = await DataSubjectRequestService(write_context.session).fulfil_request(
        request_id=request_id,
        reviewer_user_id=actor.user.id,
        audit_context=build_audit_context_from_request(
            actor_user_id=actor.user.id, request=request
        ),
    )
    return PlatformDataSubjectRequestResponse.model_validate(row)

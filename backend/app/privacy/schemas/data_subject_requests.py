from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason_payload
from app.privacy.models.data_subject_request import (
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)


class CreateDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_type: DataSubjectRequestType


class DataSubjectRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_type: DataSubjectRequestType
    status: DataSubjectRequestStatus
    requester_user_id: UUID | None
    subject_user_id: UUID | None
    submitted_at: datetime
    acknowledged_at: datetime | None
    reviewed_at: datetime | None
    decided_at: datetime | None
    fulfilled_at: datetime | None
    cancelled_at: datetime | None
    due_at: datetime
    extended_until: datetime | None
    decision_reason_code: str | None
    rejection_reason_code: str | None
    extension_reason_code: str | None
    created_at: datetime
    updated_at: datetime


class DataSubjectRequestsMeta(BaseModel):
    total: int
    limit: int
    offset: int


class DataSubjectRequestsCollectionResponse(BaseModel):
    data: list[DataSubjectRequestResponse]
    meta: DataSubjectRequestsMeta
    links: dict[str, str]


class PlatformDataSubjectRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_type: DataSubjectRequestType
    status: DataSubjectRequestStatus
    requester_user_id: UUID | None
    subject_user_id: UUID | None
    reviewer_user_id: UUID | None
    submitted_at: datetime
    acknowledged_at: datetime | None
    reviewed_at: datetime | None
    decided_at: datetime | None
    fulfilled_at: datetime | None
    cancelled_at: datetime | None
    due_at: datetime
    extended_until: datetime | None
    decision_reason_code: str | None
    rejection_reason_code: str | None
    extension_reason_code: str | None
    created_at: datetime
    updated_at: datetime


class PlatformDataSubjectRequestsMeta(BaseModel):
    total: int
    limit: int
    offset: int


class PlatformDataSubjectRequestsCollectionResponse(BaseModel):
    data: list[PlatformDataSubjectRequestResponse]
    meta: PlatformDataSubjectRequestsMeta
    links: dict[str, str]


class ReviewDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApproveDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: OperationalReasonCode | None = None

    @model_validator(mode="before")
    @classmethod
    def normalise_legacy_reason_alias(cls, data: object) -> object:
        return normalise_legacy_reason_payload(data, required=False)


class RejectDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: OperationalReasonCode

    @model_validator(mode="before")
    @classmethod
    def normalise_legacy_reason_alias(cls, data: object) -> object:
        return normalise_legacy_reason_payload(data, required=True)


class CancelDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FulfilDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.audit.reasons import OperationalReasonCode, normalise_legacy_reason_payload
from app.privacy.models.data_subject_request import (
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestRepresentativeStatus,
    DataSubjectRequestRequesterRole,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)

REQUESTER_NOTE_MAX_LENGTH = 2000
REPRESENTATIVE_RELATIONSHIP_MAX_LENGTH = 64
REPRESENTATIVE_AUTHORITY_NOTE_MAX_LENGTH = 2000


class CreateDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_type: DataSubjectRequestType
    requester_note: str | None = Field(
        default=None,
        max_length=REQUESTER_NOTE_MAX_LENGTH,
        description="Optional requester-provided details for platform review.",
    )
    subject_user_id: UUID | None = Field(
        default=None,
        description=(
            "Subject user for authorised-representative requests only. "
            "Self-service requests infer the authenticated user."
        ),
    )
    requester_role: DataSubjectRequestRequesterRole = Field(
        default=DataSubjectRequestRequesterRole.SELF,
        description="Whether the requester acts for themselves or as a representative.",
    )
    representative_relationship: str | None = Field(
        default=None,
        max_length=REPRESENTATIVE_RELATIONSHIP_MAX_LENGTH,
        description="Relationship to the subject for representative requests.",
    )
    representative_authority_note: str | None = Field(
        default=None,
        max_length=REPRESENTATIVE_AUTHORITY_NOTE_MAX_LENGTH,
        description="Authority details for platform representative review.",
    )

    @field_validator(
        "requester_note",
        "representative_relationship",
        "representative_authority_note",
        mode="before",
    )
    @classmethod
    def normalise_optional_text(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str):
            normalised = value.strip()
            return normalised or None
        return value

    @model_validator(mode="after")
    def validate_representative_payload(self) -> CreateDataSubjectRequest:
        if self.requester_role is DataSubjectRequestRequesterRole.SELF:
            if self.subject_user_id is not None:
                raise ValueError(
                    "subject_user_id is only allowed for representative requests"
                )
            if self.representative_relationship is not None:
                raise ValueError(
                    "representative_relationship is only allowed for "
                    "representative requests"
                )
            if self.representative_authority_note is not None:
                raise ValueError(
                    "representative_authority_note is only allowed for "
                    "representative requests"
                )
            return self

        if self.subject_user_id is None:
            raise ValueError("subject_user_id is required for representative requests")
        if self.representative_relationship is None:
            raise ValueError(
                "representative_relationship is required for representative requests"
            )
        if self.representative_authority_note is None:
            raise ValueError(
                "representative_authority_note is required for representative requests"
            )
        return self


class DataSubjectRequestResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    request_type: DataSubjectRequestType
    status: DataSubjectRequestStatus
    execution_status: DataSubjectRequestExecutionStatus
    execution_started_at: datetime | None
    execution_completed_at: datetime | None
    execution_failed_at: datetime | None
    execution_failure_reason_code: str | None
    requester_user_id: UUID | None
    subject_user_id: UUID | None
    requester_role: DataSubjectRequestRequesterRole
    representative_status: DataSubjectRequestRepresentativeStatus
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
    execution_status: DataSubjectRequestExecutionStatus
    execution_started_at: datetime | None
    execution_completed_at: datetime | None
    execution_failed_at: datetime | None
    execution_failure_reason_code: str | None
    requester_user_id: UUID | None
    subject_user_id: UUID | None
    reviewer_user_id: UUID | None
    requester_role: DataSubjectRequestRequesterRole
    representative_status: DataSubjectRequestRepresentativeStatus
    representative_relationship: str | None
    representative_authority_note: str | None
    representative_verified_at: datetime | None
    representative_verified_by_user_id: UUID | None
    representative_rejection_reason_code: str | None
    requester_note: str | None
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


class VerifyRepresentativeAuthority(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason_code: OperationalReasonCode | None = None

    @model_validator(mode="before")
    @classmethod
    def normalise_legacy_reason_alias(cls, data: object) -> object:
        return normalise_legacy_reason_payload(data, required=False)


class RejectRepresentativeAuthority(BaseModel):
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


class ExecuteErasureDataSubjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

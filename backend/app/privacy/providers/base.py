from __future__ import annotations

from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class PrivacyExportRecordKind(StrEnum):
    DATA = "data"
    REFERENCE = "reference"
    METADATA = "metadata"
    REDACTION_NOTICE = "redaction_notice"


class PrivacyErasureDecision(StrEnum):
    ANONYMISE = "anonymise"
    DELETE = "delete"
    RETAIN = "retain"
    MANUAL_REVIEW = "manual_review"


@dataclass(frozen=True, slots=True)
class PrivacyProviderContext:
    data_subject_request_id: UUID
    subject_user_id: UUID
    requester_user_id: UUID | None
    schema_version: str


@dataclass(frozen=True, slots=True)
class PrivacyExportRecord:
    provider_key: str
    table_name: str
    record_kind: PrivacyExportRecordKind
    payload: Mapping[str, object]
    redacted_fields: Sequence[str] = ()


@dataclass(frozen=True, slots=True)
class PrivacyErasurePlanItem:
    provider_key: str
    table_name: str
    decision: PrivacyErasureDecision
    field_names: Sequence[str]
    reason_code: str


@dataclass(frozen=True, slots=True)
class PrivacyErasurePlan:
    provider_key: str
    subject_user_id: UUID
    items: Sequence[PrivacyErasurePlanItem]


@dataclass(frozen=True, slots=True)
class PrivacyErasureResult:
    provider_key: str
    subject_user_id: UUID
    anonymised_records: int = 0
    deleted_records: int = 0
    retained_records: int = 0
    manual_review_records: int = 0


class PrivacyExportProvider(Protocol):
    provider_key: str
    table_name: str

    def iter_export_records(
        self, context: PrivacyProviderContext
    ) -> AsyncIterator[PrivacyExportRecord]: ...


class PrivacyErasureProvider(Protocol):
    provider_key: str
    table_name: str

    async def plan_erasure(
        self, context: PrivacyProviderContext
    ) -> PrivacyErasurePlan: ...

    async def apply_erasure(
        self, context: PrivacyProviderContext, plan: PrivacyErasurePlan
    ) -> PrivacyErasureResult: ...

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.privacy.erasures.plan import (
    ErasureExecutionMode,
    ErasureProviderPlanEntry,
    build_erasure_provider_plan,
)
from app.privacy.models.data_subject_request import DataSubjectRequestType


class ErasurePreviewReadiness(StrEnum):
    AUTOMATIC = "automatic"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    RETAIN_ONLY = "retain_only"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class ErasurePreviewEntry:
    provider_key: str
    table_name: str
    execution_mode: ErasureExecutionMode
    retention_policy_key: str
    readiness: ErasurePreviewReadiness
    requires_manual_review: bool

    @property
    def is_mutating(self) -> bool:
        return self.execution_mode in {
            ErasureExecutionMode.ANONYMISE,
            ErasureExecutionMode.DELETE_WHEN_ALLOWED,
            ErasureExecutionMode.RETAIN_AND_MINIMISE,
        }

    @property
    def can_run_automatically(self) -> bool:
        return self.readiness is ErasurePreviewReadiness.AUTOMATIC


@dataclass(frozen=True, slots=True)
class ErasurePreview:
    request_id: UUID
    subject_user_id: UUID
    request_type: DataSubjectRequestType
    entries: tuple[ErasurePreviewEntry, ...]

    @property
    def blocked_by_manual_review(self) -> bool:
        return any(entry.requires_manual_review for entry in self.entries)

    @property
    def automatic_provider_keys(self) -> tuple[str, ...]:
        return tuple(
            entry.provider_key
            for entry in self.entries
            if entry.readiness is ErasurePreviewReadiness.AUTOMATIC
        )

    @property
    def manual_review_provider_keys(self) -> tuple[str, ...]:
        return tuple(
            entry.provider_key
            for entry in self.entries
            if entry.readiness is ErasurePreviewReadiness.MANUAL_REVIEW_REQUIRED
        )

    @property
    def retain_only_provider_keys(self) -> tuple[str, ...]:
        return tuple(
            entry.provider_key
            for entry in self.entries
            if entry.readiness is ErasurePreviewReadiness.RETAIN_ONLY
        )

    @property
    def not_applicable_provider_keys(self) -> tuple[str, ...]:
        return tuple(
            entry.provider_key
            for entry in self.entries
            if entry.readiness is ErasurePreviewReadiness.NOT_APPLICABLE
        )


def build_erasure_preview(
    *,
    request_id: UUID,
    subject_user_id: UUID,
    request_type: DataSubjectRequestType | str,
    plan: tuple[ErasureProviderPlanEntry, ...] | None = None,
) -> ErasurePreview:
    parsed_request_type = DataSubjectRequestType(request_type)
    if parsed_request_type is not DataSubjectRequestType.ERASE:
        raise ValueError("erasure_preview_requires_erase_request")

    plan_entries = plan if plan is not None else build_erasure_provider_plan()
    preview_entries = tuple(_preview_entry(entry) for entry in plan_entries)

    return ErasurePreview(
        request_id=request_id,
        subject_user_id=subject_user_id,
        request_type=parsed_request_type,
        entries=preview_entries,
    )


def _preview_entry(plan_entry: ErasureProviderPlanEntry) -> ErasurePreviewEntry:
    return ErasurePreviewEntry(
        provider_key=plan_entry.provider_key,
        table_name=plan_entry.table_name,
        execution_mode=plan_entry.execution_mode,
        retention_policy_key=plan_entry.retention_policy_key,
        readiness=_readiness_for_plan_entry(plan_entry),
        requires_manual_review=plan_entry.requires_manual_review,
    )


def _readiness_for_plan_entry(
    plan_entry: ErasureProviderPlanEntry,
) -> ErasurePreviewReadiness:
    if plan_entry.requires_manual_review:
        return ErasurePreviewReadiness.MANUAL_REVIEW_REQUIRED
    if plan_entry.execution_mode is ErasureExecutionMode.NOT_APPLICABLE:
        return ErasurePreviewReadiness.NOT_APPLICABLE
    if plan_entry.execution_mode is ErasureExecutionMode.RETAIN_WITH_LEGAL_BASIS:
        return ErasurePreviewReadiness.RETAIN_ONLY
    return ErasurePreviewReadiness.AUTOMATIC

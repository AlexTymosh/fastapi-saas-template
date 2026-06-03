from __future__ import annotations

from uuid import uuid4

import pytest

from app.privacy.data_inventory import PrivacyErasureStrategy
from app.privacy.erasures.plan import (
    ErasureExecutionMode,
    ErasureProviderPlanEntry,
    build_erasure_provider_plan,
)
from app.privacy.erasures.preview import (
    ErasurePreviewReadiness,
    build_erasure_preview,
)
from app.privacy.models.data_subject_request import DataSubjectRequestType

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


def test_erasure_preview_rejects_non_erase_request_types() -> None:
    with pytest.raises(ValueError, match="erasure_preview_requires_erase_request"):
        build_erasure_preview(
            request_id=uuid4(),
            subject_user_id=uuid4(),
            request_type=DataSubjectRequestType.EXPORT,
        )


def test_erasure_preview_covers_every_planned_erasure_provider() -> None:
    plan = build_erasure_provider_plan()
    preview = build_erasure_preview(
        request_id=uuid4(),
        subject_user_id=uuid4(),
        request_type=DataSubjectRequestType.ERASE,
        plan=plan,
    )

    assert tuple(entry.provider_key for entry in preview.entries) == tuple(
        entry.provider_key for entry in plan
    )
    assert preview.request_type is DataSubjectRequestType.ERASE


def test_erasure_preview_marks_manual_review_entries_as_blocking() -> None:
    preview = build_erasure_preview(
        request_id=uuid4(),
        subject_user_id=uuid4(),
        request_type="erase",
    )

    manual_entries = [
        entry for entry in preview.entries if entry.requires_manual_review
    ]

    assert manual_entries
    assert preview.blocked_by_manual_review is True
    assert set(preview.manual_review_provider_keys) <= {
        entry.provider_key for entry in manual_entries
    }
    assert all(
        entry.requires_manual_review
        for entry in preview.entries
        if entry.readiness is ErasurePreviewReadiness.MANUAL_REVIEW_REQUIRED
    )


def test_erasure_preview_keeps_automatic_mutations_separate() -> None:
    preview = build_erasure_preview(
        request_id=uuid4(),
        subject_user_id=uuid4(),
        request_type=DataSubjectRequestType.ERASE,
    )

    automatic_entries = [
        entry for entry in preview.entries if entry.can_run_automatically
    ]

    assert automatic_entries
    assert tuple(entry.provider_key for entry in automatic_entries) == (
        preview.automatic_provider_keys
    )
    assert all(entry.is_mutating for entry in automatic_entries)
    assert all(
        entry.execution_mode
        in {
            ErasureExecutionMode.ANONYMISE,
            ErasureExecutionMode.DELETE_WHEN_ALLOWED,
            ErasureExecutionMode.RETAIN_AND_MINIMISE,
        }
        for entry in automatic_entries
    )


def test_erasure_preview_preserves_retain_only_classification() -> None:
    plan = (
        ErasureProviderPlanEntry(
            provider_key="organisations.review_subject_references",
            table_name="organisations",
            strategy=PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
            execution_mode=ErasureExecutionMode.RETAIN_WITH_LEGAL_BASIS,
            retention_policy_key="tenant_profile",
            requires_manual_review=True,
        ),
    )
    preview = build_erasure_preview(
        request_id=uuid4(),
        subject_user_id=uuid4(),
        request_type=DataSubjectRequestType.ERASE,
        plan=plan,
    )

    entry = preview.entries[0]

    assert entry.readiness is ErasurePreviewReadiness.RETAIN_ONLY
    assert entry.requires_manual_review is True
    assert preview.retain_only_provider_keys == (entry.provider_key,)
    assert preview.manual_review_provider_keys == ()
    assert preview.blocked_by_manual_review is True


def test_erasure_preview_exposes_non_mutating_provider_groups() -> None:
    preview = build_erasure_preview(
        request_id=uuid4(),
        subject_user_id=uuid4(),
        request_type=DataSubjectRequestType.ERASE,
    )

    retain_only_keys = {
        entry.provider_key
        for entry in preview.entries
        if entry.readiness is ErasurePreviewReadiness.RETAIN_ONLY
    }
    not_applicable_keys = {
        entry.provider_key
        for entry in preview.entries
        if entry.readiness is ErasurePreviewReadiness.NOT_APPLICABLE
    }

    assert retain_only_keys
    assert set(preview.retain_only_provider_keys) == retain_only_keys
    assert set(preview.not_applicable_provider_keys) == not_applicable_keys
    assert not retain_only_keys.intersection(preview.manual_review_provider_keys)

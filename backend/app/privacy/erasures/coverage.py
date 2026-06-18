from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.privacy.data_inventory import PRIVACY_DATA_INVENTORY
from app.privacy.provider_keys import (
    PrivacyErasureProviderKey,
    erasure_provider_table_name,
)


class ErasureCoverageDecision(StrEnum):
    EXECUTABLE = "executable"
    RETAIN_BY_POLICY = "retain_by_policy"
    MANUAL_REVIEW_POLICY = "manual_review_policy"


@dataclass(frozen=True, slots=True)
class ErasureCoverageEntry:
    provider_key: str
    table_name: str
    decision: ErasureCoverageDecision
    rationale: str


def _entry(
    provider_key: PrivacyErasureProviderKey,
    *,
    decision: ErasureCoverageDecision,
    rationale: str,
) -> ErasureCoverageEntry:
    return ErasureCoverageEntry(
        provider_key=provider_key.value,
        table_name=erasure_provider_table_name(provider_key.value),
        decision=decision,
        rationale=rationale,
    )


_ERASURE_COVERAGE_ENTRIES: tuple[ErasureCoverageEntry, ...] = (
    _entry(
        PrivacyErasureProviderKey.USERS_ANONYMISE_PROFILE,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale="Subject profile direct identifiers are anonymised in-place.",
    ),
    _entry(
        PrivacyErasureProviderKey.MEMBERSHIPS_MINIMISE_SUBJECT_LINK,
        decision=ErasureCoverageDecision.RETAIN_BY_POLICY,
        rationale=(
            "Membership rows preserve tenant integrity; the linked user profile is "
            "anonymised while membership history is retained."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.ORGANISATIONS_REVIEW_SUBJECT_REFERENCES,
        decision=ErasureCoverageDecision.MANUAL_REVIEW_POLICY,
        rationale=(
            "Organisation records are tenant-owned and are retained; subject-linked "
            "operational reason fields remain visible in erasure preview for review."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.INVITES_ANONYMISE_OR_PURGE_SUBJECT_REFERENCES,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Invite contact identifiers and token material are anonymised or purged."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.OUTBOX_PURGE_OR_SCRUB_PAYLOAD,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Subject-linked outbox payload values are scrubbed before profile erasure."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.AUDIT_MINIMISE_SUBJECT_ACTOR_OR_TARGET_IDENTIFIERS,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Audit rows are retained for integrity while subject identifiers "
            "are minimised."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.PLATFORM_STAFF_MINIMISE_SUBJECT_OR_CREATOR_LINKS,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Platform staff records are retained for access-control accountability; "
            "creator links and free-text suspension context are minimised "
            "when possible."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.DSR_MINIMISE_WORKFLOW_IDENTIFIERS,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "DSR lifecycle evidence is retained. Subject/requester-owned rows "
            "minimise user links, workflow relationship links and unsafe "
            "notes/idempotency metadata; reviewer-only rows minimise only the "
            "reviewer link."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.EXPORT_ARTIFACTS_DELETE_OBJECT_MINIMISE_METADATA,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Subject-owned export objects are deleted after erasure DB changes "
            "commit. Subject-owned artifacts with storage keys are marked as "
            "non-downloadable retry candidates until cleanup confirms object "
            "deletion. Non-processing actor identifier links are minimised without "
            "deleting other subjects' artifacts; processing actor-linked artifacts "
            "block erasure until the worker lease completes."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_AUTHORIZATIONS,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Lawful-basis evidence is retained; optional collection source context "
            "is minimised."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_CONSENT_RECORDS,
        decision=ErasureCoverageDecision.RETAIN_BY_POLICY,
        rationale=(
            "Consent grant/withdrawal evidence is retained under privacy "
            "governance policy."
        ),
    ),
    _entry(
        PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_NOTICE_ACCEPTANCES,
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Notice acceptance evidence is retained while optional source context "
            "is minimised."
        ),
    ),
)

ERASURE_COVERAGE_MAP: dict[str, ErasureCoverageEntry] = {
    entry.provider_key: entry for entry in _ERASURE_COVERAGE_ENTRIES
}


def inventory_erasure_provider_keys() -> frozenset[str]:
    return frozenset(
        entry.erasure_provider_key
        for entry in PRIVACY_DATA_INVENTORY
        if entry.erasure_provider_key is not None
    )


def executable_erasure_provider_keys() -> frozenset[str]:
    return frozenset(
        provider_key
        for provider_key, entry in ERASURE_COVERAGE_MAP.items()
        if entry.decision is ErasureCoverageDecision.EXECUTABLE
    )

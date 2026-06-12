from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.privacy.data_inventory import PRIVACY_DATA_INVENTORY


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


ERASURE_COVERAGE_MAP: dict[str, ErasureCoverageEntry] = {
    "users.anonymise_profile": ErasureCoverageEntry(
        provider_key="users.anonymise_profile",
        table_name="users",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale="Subject profile direct identifiers are anonymised in-place.",
    ),
    "memberships.minimise_subject_link": ErasureCoverageEntry(
        provider_key="memberships.minimise_subject_link",
        table_name="memberships",
        decision=ErasureCoverageDecision.RETAIN_BY_POLICY,
        rationale=(
            "Membership rows preserve tenant integrity; the linked user profile is "
            "anonymised while membership history is retained."
        ),
    ),
    "organisations.review_subject_references": ErasureCoverageEntry(
        provider_key="organisations.review_subject_references",
        table_name="organisations",
        decision=ErasureCoverageDecision.MANUAL_REVIEW_POLICY,
        rationale=(
            "Organisation records are tenant-owned and are retained; subject-linked "
            "operational reason fields remain visible in erasure preview for review."
        ),
    ),
    "invites.anonymise_or_purge_subject_references": ErasureCoverageEntry(
        provider_key="invites.anonymise_or_purge_subject_references",
        table_name="invites",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Invite contact identifiers and token material are anonymised or purged."
        ),
    ),
    "outbox.purge_or_scrub_payload": ErasureCoverageEntry(
        provider_key="outbox.purge_or_scrub_payload",
        table_name="outbox_events",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Subject-linked outbox payload values are scrubbed before profile erasure."
        ),
    ),
    "audit.minimise_subject_actor_or_target_identifiers": ErasureCoverageEntry(
        provider_key="audit.minimise_subject_actor_or_target_identifiers",
        table_name="audit_events",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Audit rows are retained for integrity while subject identifiers "
            "are minimised."
        ),
    ),
    "platform_staff.minimise_subject_or_creator_links": ErasureCoverageEntry(
        provider_key="platform_staff.minimise_subject_or_creator_links",
        table_name="platform_staff",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Platform staff records are retained for access-control accountability; "
            "creator links and free-text suspension context are minimised "
            "when possible."
        ),
    ),
    "dsr.minimise_workflow_identifiers": ErasureCoverageEntry(
        provider_key="dsr.minimise_workflow_identifiers",
        table_name="data_subject_requests",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "DSR lifecycle evidence is retained while subject/requester/reviewer links "
            "and unsafe notes/idempotency metadata are minimised."
        ),
    ),
    "export_artifacts.delete_object_minimise_subject_or_actor_metadata": (
        ErasureCoverageEntry(
            provider_key=(
                "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
            ),
            table_name="export_artifacts",
            decision=ErasureCoverageDecision.EXECUTABLE,
            rationale=(
                "Subject-owned export objects are deleted after erasure DB "
                "changes commit. Downloadable subject-owned artifacts are "
                "cancelled first and retain storage keys as non-downloadable "
                "retry markers until cleanup confirms object deletion. "
                "Non-processing actor identifier links are minimised without "
                "deleting other subjects' artifacts; processing actor-linked "
                "artifacts block erasure until the worker lease completes."
            ),
        )
    ),
    "privacy_governance.minimise_authorizations": ErasureCoverageEntry(
        provider_key="privacy_governance.minimise_authorizations",
        table_name="data_processing_authorizations",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Lawful-basis evidence is retained; optional collection source context is "
            "minimised."
        ),
    ),
    "privacy_governance.minimise_consent_records": ErasureCoverageEntry(
        provider_key="privacy_governance.minimise_consent_records",
        table_name="consent_records",
        decision=ErasureCoverageDecision.RETAIN_BY_POLICY,
        rationale=(
            "Consent grant/withdrawal evidence is retained under privacy "
            "governance policy."
        ),
    ),
    "privacy_governance.minimise_notice_acceptances": ErasureCoverageEntry(
        provider_key="privacy_governance.minimise_notice_acceptances",
        table_name="privacy_notice_acceptances",
        decision=ErasureCoverageDecision.EXECUTABLE,
        rationale=(
            "Notice acceptance evidence is retained while optional source "
            "context is minimised."
        ),
    ),
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

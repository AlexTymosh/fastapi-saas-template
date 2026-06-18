from __future__ import annotations

from enum import StrEnum


class PrivacyExportProviderKey(StrEnum):
    USERS_PROFILE = "users.profile"
    MEMBERSHIPS_BY_SUBJECT = "memberships.by_subject"
    ORGANISATIONS_BY_SUBJECT_MEMBERSHIP = "organisations.by_subject_membership"
    INVITES_BY_SUBJECT_EMAIL_OR_REVOKER = "invites.by_subject_email_or_revoker"
    OUTBOX_SUBJECT_REFERENCES = "outbox.subject_references"
    AUDIT_SUBJECT_ACTOR_OR_TARGET_JOIN_EVENTS = (
        "audit.subject_actor_or_target_join_events"
    )
    PLATFORM_STAFF_BY_SUBJECT_OR_CREATOR = "platform_staff.by_subject_or_creator"
    DSR_WORKFLOW_RECORDS = "dsr.workflow_records"
    EXPORT_ARTIFACTS_SUBJECT_OR_ACTOR_METADATA = (
        "export_artifacts.subject_or_actor_metadata"
    )
    PRIVACY_GOVERNANCE_AUTHORIZATIONS = "privacy_governance.authorizations"
    PRIVACY_GOVERNANCE_CONSENT_RECORDS = "privacy_governance.consent_records"
    PRIVACY_GOVERNANCE_NOTICE_ACCEPTANCES = "privacy_governance.notice_acceptances"


class PrivacyErasureProviderKey(StrEnum):
    USERS_ANONYMISE_PROFILE = "users.anonymise_profile"
    MEMBERSHIPS_MINIMISE_SUBJECT_LINK = "memberships.minimise_subject_link"
    ORGANISATIONS_REVIEW_SUBJECT_REFERENCES = "organisations.review_subject_references"
    INVITES_ANONYMISE_OR_PURGE_SUBJECT_REFERENCES = (
        "invites.anonymise_or_purge_subject_references"
    )
    OUTBOX_PURGE_OR_SCRUB_PAYLOAD = "outbox.purge_or_scrub_payload"
    AUDIT_MINIMISE_SUBJECT_ACTOR_OR_TARGET_IDENTIFIERS = (
        "audit.minimise_subject_actor_or_target_identifiers"
    )
    PLATFORM_STAFF_MINIMISE_SUBJECT_OR_CREATOR_LINKS = (
        "platform_staff.minimise_subject_or_creator_links"
    )
    DSR_MINIMISE_WORKFLOW_IDENTIFIERS = "dsr.minimise_workflow_identifiers"
    EXPORT_ARTIFACTS_DELETE_OBJECT_MINIMISE_METADATA = (
        "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
    )
    PRIVACY_GOVERNANCE_MINIMISE_AUTHORIZATIONS = (
        "privacy_governance.minimise_authorizations"
    )
    PRIVACY_GOVERNANCE_MINIMISE_CONSENT_RECORDS = (
        "privacy_governance.minimise_consent_records"
    )
    PRIVACY_GOVERNANCE_MINIMISE_NOTICE_ACCEPTANCES = (
        "privacy_governance.minimise_notice_acceptances"
    )


_EXPORT_PROVIDER_TABLES: dict[PrivacyExportProviderKey, str] = {
    PrivacyExportProviderKey.USERS_PROFILE: "users",
    PrivacyExportProviderKey.MEMBERSHIPS_BY_SUBJECT: "memberships",
    PrivacyExportProviderKey.ORGANISATIONS_BY_SUBJECT_MEMBERSHIP: "organisations",
    PrivacyExportProviderKey.INVITES_BY_SUBJECT_EMAIL_OR_REVOKER: "invites",
    PrivacyExportProviderKey.OUTBOX_SUBJECT_REFERENCES: "outbox_events",
    PrivacyExportProviderKey.AUDIT_SUBJECT_ACTOR_OR_TARGET_JOIN_EVENTS: (
        "audit_events"
    ),
    PrivacyExportProviderKey.PLATFORM_STAFF_BY_SUBJECT_OR_CREATOR: ("platform_staff"),
    PrivacyExportProviderKey.DSR_WORKFLOW_RECORDS: "data_subject_requests",
    PrivacyExportProviderKey.EXPORT_ARTIFACTS_SUBJECT_OR_ACTOR_METADATA: (
        "export_artifacts"
    ),
    PrivacyExportProviderKey.PRIVACY_GOVERNANCE_AUTHORIZATIONS: (
        "data_processing_authorizations"
    ),
    PrivacyExportProviderKey.PRIVACY_GOVERNANCE_CONSENT_RECORDS: ("consent_records"),
    PrivacyExportProviderKey.PRIVACY_GOVERNANCE_NOTICE_ACCEPTANCES: (
        "privacy_notice_acceptances"
    ),
}

_ERASURE_PROVIDER_TABLES: dict[PrivacyErasureProviderKey, str] = {
    PrivacyErasureProviderKey.USERS_ANONYMISE_PROFILE: "users",
    PrivacyErasureProviderKey.MEMBERSHIPS_MINIMISE_SUBJECT_LINK: "memberships",
    PrivacyErasureProviderKey.ORGANISATIONS_REVIEW_SUBJECT_REFERENCES: (
        "organisations"
    ),
    PrivacyErasureProviderKey.INVITES_ANONYMISE_OR_PURGE_SUBJECT_REFERENCES: (
        "invites"
    ),
    PrivacyErasureProviderKey.OUTBOX_PURGE_OR_SCRUB_PAYLOAD: "outbox_events",
    PrivacyErasureProviderKey.AUDIT_MINIMISE_SUBJECT_ACTOR_OR_TARGET_IDENTIFIERS: (
        "audit_events"
    ),
    PrivacyErasureProviderKey.PLATFORM_STAFF_MINIMISE_SUBJECT_OR_CREATOR_LINKS: (
        "platform_staff"
    ),
    PrivacyErasureProviderKey.DSR_MINIMISE_WORKFLOW_IDENTIFIERS: (
        "data_subject_requests"
    ),
    PrivacyErasureProviderKey.EXPORT_ARTIFACTS_DELETE_OBJECT_MINIMISE_METADATA: (
        "export_artifacts"
    ),
    PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_AUTHORIZATIONS: (
        "data_processing_authorizations"
    ),
    PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_CONSENT_RECORDS: (
        "consent_records"
    ),
    PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_NOTICE_ACCEPTANCES: (
        "privacy_notice_acceptances"
    ),
}

_ERASURE_ORCHESTRATION_ORDER: tuple[PrivacyErasureProviderKey, ...] = (
    PrivacyErasureProviderKey.AUDIT_MINIMISE_SUBJECT_ACTOR_OR_TARGET_IDENTIFIERS,
    PrivacyErasureProviderKey.OUTBOX_PURGE_OR_SCRUB_PAYLOAD,
    PrivacyErasureProviderKey.INVITES_ANONYMISE_OR_PURGE_SUBJECT_REFERENCES,
    PrivacyErasureProviderKey.MEMBERSHIPS_MINIMISE_SUBJECT_LINK,
    PrivacyErasureProviderKey.ORGANISATIONS_REVIEW_SUBJECT_REFERENCES,
    PrivacyErasureProviderKey.PLATFORM_STAFF_MINIMISE_SUBJECT_OR_CREATOR_LINKS,
    PrivacyErasureProviderKey.EXPORT_ARTIFACTS_DELETE_OBJECT_MINIMISE_METADATA,
    PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_AUTHORIZATIONS,
    PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_CONSENT_RECORDS,
    PrivacyErasureProviderKey.PRIVACY_GOVERNANCE_MINIMISE_NOTICE_ACCEPTANCES,
    PrivacyErasureProviderKey.USERS_ANONYMISE_PROFILE,
    PrivacyErasureProviderKey.DSR_MINIMISE_WORKFLOW_IDENTIFIERS,
)


def export_provider_keys() -> frozenset[str]:
    return frozenset(provider_key.value for provider_key in PrivacyExportProviderKey)


def erasure_provider_keys() -> frozenset[str]:
    return frozenset(provider_key.value for provider_key in PrivacyErasureProviderKey)


def erasure_orchestration_provider_order() -> tuple[str, ...]:
    return tuple(provider_key.value for provider_key in _ERASURE_ORCHESTRATION_ORDER)


def export_provider_table_name(provider_key: str) -> str:
    return _EXPORT_PROVIDER_TABLES[PrivacyExportProviderKey(provider_key)]


def erasure_provider_table_name(provider_key: str) -> str:
    return _ERASURE_PROVIDER_TABLES[PrivacyErasureProviderKey(provider_key)]

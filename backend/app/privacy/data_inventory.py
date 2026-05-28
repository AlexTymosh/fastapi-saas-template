from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PrivacyDataCategory(StrEnum):
    ACCOUNT_PROFILE = "account_profile"
    CONTACT = "contact"
    MEMBERSHIP = "membership"
    ORGANISATION = "organisation"
    INVITE = "invite"
    OUTBOX = "outbox"
    AUDIT = "audit"
    PLATFORM_STAFF = "platform_staff"
    PRIVACY_GOVERNANCE = "privacy_governance"
    DSR_WORKFLOW = "dsr_workflow"
    EXPORT_ARTIFACT = "export_artifact"


class PrivacyFieldClassification(StrEnum):
    DIRECT_IDENTIFIER = "direct_identifier"
    INDIRECT_IDENTIFIER = "indirect_identifier"
    CONTACT_POINT = "contact_point"
    SECRET_OR_TOKEN = "secret_or_token"
    OPERATIONAL_REASON = "operational_reason"
    NETWORK_IDENTIFIER = "network_identifier"
    USER_AGENT = "user_agent"
    RELATIONSHIP = "relationship"
    LIFECYCLE = "lifecycle"
    STRUCTURED_METADATA = "structured_metadata"


class PrivacyFieldErasureAction(StrEnum):
    ANONYMISE = "anonymise"
    DELETE = "delete"
    RETAIN = "retain"
    RETAIN_MINIMISED = "retain_minimised"
    REMOVE_PAYLOAD_VALUE = "remove_payload_value"
    REVIEW_REQUIRED = "review_required"


class PrivacyErasureStrategy(StrEnum):
    ANONYMISE_SUBJECT = "anonymise_subject"
    DELETE_WHEN_ALLOWED = "delete_when_allowed"
    RETAIN_AND_MINIMISE = "retain_and_minimise"
    RETAIN_WITH_LEGAL_BASIS = "retain_with_legal_basis"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class PrivacyFieldInventory:
    name: str
    classification: PrivacyFieldClassification
    export: bool
    erasure_action: PrivacyFieldErasureAction
    notes: str


@dataclass(frozen=True, slots=True)
class PrivacyTableInventoryEntry:
    table_name: str
    model_module: str
    model_name: str
    subject_locator: str
    data_categories: tuple[PrivacyDataCategory, ...]
    fields: tuple[PrivacyFieldInventory, ...]
    export_provider_key: str
    erasure_provider_key: str | None
    erasure_strategy: PrivacyErasureStrategy
    retention_policy_key: str
    notes: str

    @property
    def model_path(self) -> str:
        return f"{self.model_module}.{self.model_name}"


@dataclass(frozen=True, slots=True)
class DsrScopeExclusion:
    table_name: str
    reason: str


PRIVACY_DATA_INVENTORY: tuple[PrivacyTableInventoryEntry, ...] = (
    PrivacyTableInventoryEntry(
        table_name="users",
        model_module="app.users.models.user",
        model_name="User",
        subject_locator="direct: users.id == subject_user_id",
        data_categories=(
            PrivacyDataCategory.ACCOUNT_PROFILE,
            PrivacyDataCategory.CONTACT,
        ),
        fields=(
            PrivacyFieldInventory(
                "id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Primary key; keep referential integrity, avoid exposing as public ID.",
            ),
            PrivacyFieldInventory(
                "external_auth_id",
                PrivacyFieldClassification.DIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.ANONYMISE,
                "External IdP linkage; remove or replace during account erasure.",
            ),
            PrivacyFieldInventory(
                "email",
                PrivacyFieldClassification.CONTACT_POINT,
                True,
                PrivacyFieldErasureAction.ANONYMISE,
                "Primary contact identifier.",
            ),
            PrivacyFieldInventory(
                "first_name",
                PrivacyFieldClassification.DIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.ANONYMISE,
                "Profile direct identifier.",
            ),
            PrivacyFieldInventory(
                "last_name",
                PrivacyFieldClassification.DIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.ANONYMISE,
                "Profile direct identifier.",
            ),
            PrivacyFieldInventory(
                "suspended_reason",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "May contain free-text personal data; prefer structured reason codes.",
            ),
        ),
        export_provider_key="users.profile",
        erasure_provider_key="users.anonymise_profile",
        erasure_strategy=PrivacyErasureStrategy.ANONYMISE_SUBJECT,
        retention_policy_key="account_profile",
        notes="Core account identity table.",
    ),
    PrivacyTableInventoryEntry(
        table_name="memberships",
        model_module="app.memberships.models.membership",
        model_name="Membership",
        subject_locator="direct: memberships.user_id == subject_user_id",
        data_categories=(PrivacyDataCategory.MEMBERSHIP,),
        fields=(
            PrivacyFieldInventory(
                "user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Subject link for membership history.",
            ),
            PrivacyFieldInventory(
                "organisation_id",
                PrivacyFieldClassification.RELATIONSHIP,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Organisation relationship may be required for tenant integrity.",
            ),
            PrivacyFieldInventory(
                "role",
                PrivacyFieldClassification.RELATIONSHIP,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Role assignment can be retained as minimised operational history.",
            ),
        ),
        export_provider_key="memberships.by_subject",
        erasure_provider_key="memberships.minimise_subject_link",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_AND_MINIMISE,
        retention_policy_key="membership_history",
        notes="Exports current and historic subject membership relationships.",
    ),
    PrivacyTableInventoryEntry(
        table_name="organisations",
        model_module="app.organisations.models.organisation",
        model_name="Organisation",
        subject_locator="indirect: organisations reached through subject memberships",
        data_categories=(PrivacyDataCategory.ORGANISATION,),
        fields=(
            PrivacyFieldInventory(
                "name",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN,
                "Tenant data, exported only when related to the subject.",
            ),
            PrivacyFieldInventory(
                "slug",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN,
                "Tenant data, not erased by a user DSR without separate tenant policy.",
            ),
            PrivacyFieldInventory(
                "suspended_reason",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "May contain personal data if staff entered free text.",
            ),
        ),
        export_provider_key="organisations.by_subject_membership",
        erasure_provider_key="organisations.review_subject_references",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
        retention_policy_key="tenant_profile",
        notes="Organisation records are tenant-owned, not subject-owned.",
    ),
    PrivacyTableInventoryEntry(
        table_name="invites",
        model_module="app.invites.models.invite",
        model_name="Invite",
        subject_locator=(
            "direct/indirect: invites.email matches subject email "
            "or invites.revoked_by_user_id == subject_user_id"
        ),
        data_categories=(PrivacyDataCategory.INVITE, PrivacyDataCategory.CONTACT),
        fields=(
            PrivacyFieldInventory(
                "email",
                PrivacyFieldClassification.CONTACT_POINT,
                True,
                PrivacyFieldErasureAction.ANONYMISE,
                "Invitee contact identifier.",
            ),
            PrivacyFieldInventory(
                "organisation_id",
                PrivacyFieldClassification.RELATIONSHIP,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Tenant relationship explaining which organisation "
                    "the subject was invited to."
                ),
            ),
            PrivacyFieldInventory(
                "role",
                PrivacyFieldClassification.RELATIONSHIP,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Invited role relationship for the pending or historical invite.",
            ),
            PrivacyFieldInventory(
                "token_hash",
                PrivacyFieldClassification.SECRET_OR_TOKEN,
                False,
                PrivacyFieldErasureAction.DELETE,
                "Never export token material; delete when invite retention allows.",
            ),
            PrivacyFieldInventory(
                "revoked_by_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Revoker-side subject link when the subject revoked another "
                    "user's invite; preserve integrity but minimise when policy permits"
                ),
            ),
        ),
        export_provider_key="invites.by_subject_email_or_revoker",
        erasure_provider_key="invites.anonymise_or_purge_subject_references",
        erasure_strategy=PrivacyErasureStrategy.DELETE_WHEN_ALLOWED,
        retention_policy_key="invite_lifecycle",
        notes="Invite records are subject data when email matches the subject.",
    ),
    PrivacyTableInventoryEntry(
        table_name="outbox_events",
        model_module="app.outbox.models.outbox_event",
        model_name="OutboxEvent",
        subject_locator=(
            "indirect: payload_json or aggregate_id references subject data"
        ),
        data_categories=(PrivacyDataCategory.OUTBOX, PrivacyDataCategory.CONTACT),
        fields=(
            PrivacyFieldInventory(
                "payload_json",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                False,
                PrivacyFieldErasureAction.REMOVE_PAYLOAD_VALUE,
                "May contain email and encrypted raw tokens; export references only.",
            ),
            PrivacyFieldInventory(
                "aggregate_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Aggregate reference can identify invite/user flows.",
            ),
            PrivacyFieldInventory(
                "last_error",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                False,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Free-text error may contain leaked PII; do not export by default.",
            ),
        ),
        export_provider_key="outbox.subject_references",
        erasure_provider_key="outbox.purge_or_scrub_payload",
        erasure_strategy=PrivacyErasureStrategy.DELETE_WHEN_ALLOWED,
        retention_policy_key="outbox_delivery",
        notes="Outbox payloads should be scrubbed after delivery/retention windows.",
    ),
    PrivacyTableInventoryEntry(
        table_name="audit_events",
        model_module="app.audit.models.audit_event",
        model_name="AuditEvent",
        subject_locator=(
            "direct: audit_events.actor_user_id == subject_user_id; "
            "direct target: target_type='user' and target_id == subject_user_id; "
            "target join: target_type='invite' and target_id -> invites.id where "
            "invites.email matches subject email or "
            "invites.revoked_by_user_id == subject_user_id; "
            "target join: target_type='membership' and target_id -> memberships.id "
            "where memberships.user_id == subject_user_id; "
            "target join: target_type='data_subject_request' and target_id -> "
            "data_subject_requests.id where requester_user_id/subject_user_id/"
            "reviewer_user_id matches subject_user_id; "
            "target join: target_type='export_artifact' and target_id -> "
            "export_artifacts.id where subject_user_id/requester_user_id/"
            "requested_by_user_id/generated_by_user_id matches subject_user_id; "
            "target join: target_type='platform_staff' and target_id -> "
            "platform_staff.id where user_id/created_by_user_id matches subject_user_id"
        ),
        data_categories=(PrivacyDataCategory.AUDIT,),
        fields=(
            PrivacyFieldInventory(
                "actor_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Preserve audit integrity; minimise after retention/legal review.",
            ),
            PrivacyFieldInventory(
                "target_type",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Target discriminator used with target_id to identify "
                    "subject-linked audit events."
                ),
            ),
            PrivacyFieldInventory(
                "target_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Target-side subject link, for example target_type='user' "
                    "and target_id == subject_user_id."
                ),
            ),
            PrivacyFieldInventory(
                "reason",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Free-text reason can contain personal/special-category data.",
            ),
            PrivacyFieldInventory(
                "metadata_json",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Export only allowlisted metadata; scrub PII where justified.",
            ),
            PrivacyFieldInventory(
                "ip_address",
                PrivacyFieldClassification.NETWORK_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Network identifier; pseudonymise/minimise according to audit policy.",
            ),
            PrivacyFieldInventory(
                "user_agent",
                PrivacyFieldClassification.USER_AGENT,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Fingerprinting risk; minimise according to audit policy.",
            ),
        ),
        export_provider_key="audit.subject_actor_or_target_join_events",
        erasure_provider_key="audit.minimise_subject_actor_or_target_identifiers",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_AND_MINIMISE,
        retention_policy_key="audit_events",
        notes=(
            "Audit logs require integrity-preserving minimisation, not blind deletion."
        ),
    ),
    PrivacyTableInventoryEntry(
        table_name="platform_staff",
        model_module="app.platform.models.platform_staff",
        model_name="PlatformStaff",
        subject_locator=(
            "direct: platform_staff.user_id == subject_user_id "
            "or platform_staff.created_by_user_id == subject_user_id"
        ),
        data_categories=(PrivacyDataCategory.PLATFORM_STAFF,),
        fields=(
            PrivacyFieldInventory(
                "user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Staff identity link.",
            ),
            PrivacyFieldInventory(
                "created_by_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Creator-side subject link when the subject created another "
                    "platform staff record."
                ),
            ),
            PrivacyFieldInventory(
                "suspended_reason",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Free-text reason may contain personal data.",
            ),
        ),
        export_provider_key="platform_staff.by_subject_or_creator",
        erasure_provider_key="platform_staff.minimise_subject_or_creator_links",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
        retention_policy_key="platform_staff_records",
        notes="Staff records have stronger legal/compliance retention constraints.",
    ),
    PrivacyTableInventoryEntry(
        table_name="data_subject_requests",
        model_module="app.privacy.models.data_subject_request",
        model_name="DataSubjectRequest",
        subject_locator="direct: subject_user_id/requester_user_id/reviewer_user_id",
        data_categories=(PrivacyDataCategory.DSR_WORKFLOW,),
        fields=(
            PrivacyFieldInventory(
                "requester_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Requester link for DSR auditability.",
            ),
            PrivacyFieldInventory(
                "subject_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Subject link for DSR auditability.",
            ),
            PrivacyFieldInventory(
                "reviewer_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Reviewer link for compliance auditability.",
            ),
            PrivacyFieldInventory(
                "requester_note",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "May contain free-text personal data if enabled by future API.",
            ),
            PrivacyFieldInventory(
                "internal_note",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                False,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Internal compliance note; do not export by default.",
            ),
        ),
        export_provider_key="dsr.workflow_records",
        erasure_provider_key="dsr.minimise_workflow_identifiers",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_AND_MINIMISE,
        retention_policy_key="dsr_compliance_records",
        notes="DSR records prove compliance and should not be blindly deleted.",
    ),
    PrivacyTableInventoryEntry(
        table_name="export_artifacts",
        model_module="app.privacy.models.export_artifact",
        model_name="ExportArtifact",
        subject_locator=(
            "direct: subject_user_id/requester_user_id "
            "or actor-side requested_by_user_id/generated_by_user_id"
        ),
        data_categories=(PrivacyDataCategory.EXPORT_ARTIFACT,),
        fields=(
            PrivacyFieldInventory(
                "subject_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Subject link for export artifact metadata.",
            ),
            PrivacyFieldInventory(
                "requester_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Requester link for access checks.",
            ),
            PrivacyFieldInventory(
                "requested_by_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Actor-side subject link when the subject requested another "
                    "user's export artifact."
                ),
            ),
            PrivacyFieldInventory(
                "generated_by_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                (
                    "Actor-side subject link when the subject generated another "
                    "user's export artifact."
                ),
            ),
            PrivacyFieldInventory(
                "storage_key",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                False,
                PrivacyFieldErasureAction.DELETE,
                "Storage locator; never expose through API/export payload.",
            ),
            PrivacyFieldInventory(
                "checksum_sha256",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Integrity metadata for generated artifact.",
            ),
        ),
        export_provider_key="export_artifacts.subject_or_actor_metadata",
        erasure_provider_key=(
            "export_artifacts.delete_object_minimise_subject_or_actor_metadata"
        ),
        erasure_strategy=PrivacyErasureStrategy.DELETE_WHEN_ALLOWED,
        retention_policy_key="export_artifacts",
        notes="Artifact binary content must be deleted after retention expiry.",
    ),
    PrivacyTableInventoryEntry(
        table_name="data_processing_authorizations",
        model_module="app.privacy.models.privacy_governance",
        model_name="DataProcessingAuthorization",
        subject_locator="direct: subject_user_id == subject_user_id",
        data_categories=(PrivacyDataCategory.PRIVACY_GOVERNANCE,),
        fields=(
            PrivacyFieldInventory(
                "subject_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Subject link for processing authorisation.",
            ),
            PrivacyFieldInventory(
                "lawful_basis",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN,
                "Compliance metadata explaining processing basis.",
            ),
            PrivacyFieldInventory(
                "source",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Source may identify how the authorisation was obtained.",
            ),
        ),
        export_provider_key="privacy_governance.authorizations",
        erasure_provider_key="privacy_governance.minimise_authorizations",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
        retention_policy_key="privacy_governance",
        notes="Needed to explain lawfulness and purpose limitation.",
    ),
    PrivacyTableInventoryEntry(
        table_name="consent_records",
        model_module="app.privacy.models.privacy_governance",
        model_name="ConsentRecord",
        subject_locator="direct: subject_user_id == subject_user_id",
        data_categories=(PrivacyDataCategory.PRIVACY_GOVERNANCE,),
        fields=(
            PrivacyFieldInventory(
                "subject_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Subject link for consent proof.",
            ),
            PrivacyFieldInventory(
                "privacy_notice_version",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN,
                "Compliance metadata.",
            ),
            PrivacyFieldInventory(
                "withdrawal_reason_code",
                PrivacyFieldClassification.OPERATIONAL_REASON,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "Structured reason today; keep free-text out of this field.",
            ),
        ),
        export_provider_key="privacy_governance.consent_records",
        erasure_provider_key="privacy_governance.minimise_consent_records",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
        retention_policy_key="privacy_governance",
        notes="Consent records are compliance evidence.",
    ),
    PrivacyTableInventoryEntry(
        table_name="privacy_notice_acceptances",
        model_module="app.privacy.models.privacy_governance",
        model_name="PrivacyNoticeAcceptance",
        subject_locator="direct: subject_user_id == subject_user_id",
        data_categories=(PrivacyDataCategory.PRIVACY_GOVERNANCE,),
        fields=(
            PrivacyFieldInventory(
                "subject_user_id",
                PrivacyFieldClassification.INDIRECT_IDENTIFIER,
                True,
                PrivacyFieldErasureAction.RETAIN_MINIMISED,
                "Subject link for notice acceptance proof.",
            ),
            PrivacyFieldInventory(
                "notice_version",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.RETAIN,
                "Compliance metadata.",
            ),
            PrivacyFieldInventory(
                "source",
                PrivacyFieldClassification.STRUCTURED_METADATA,
                True,
                PrivacyFieldErasureAction.REVIEW_REQUIRED,
                "May identify the channel where notice was accepted.",
            ),
        ),
        export_provider_key="privacy_governance.notice_acceptances",
        erasure_provider_key="privacy_governance.minimise_notice_acceptances",
        erasure_strategy=PrivacyErasureStrategy.RETAIN_WITH_LEGAL_BASIS,
        retention_policy_key="privacy_governance",
        notes="Notice acceptance records are compliance evidence.",
    ),
)

DSR_SCOPE_EXCLUDED_TABLES: tuple[DsrScopeExclusion, ...] = (
    DsrScopeExclusion(
        table_name="processing_purposes",
        reason="Static processing-purpose catalogue; no subject identifier column.",
    ),
)


ISSUE_328_CORE_TABLES = frozenset(
    {
        "users",
        "memberships",
        "organisations",
        "invites",
        "outbox_events",
        "audit_events",
    }
)


def get_privacy_inventory_by_table() -> dict[str, PrivacyTableInventoryEntry]:
    return {entry.table_name: entry for entry in PRIVACY_DATA_INVENTORY}


def get_dsr_scope_exclusions_by_table() -> dict[str, DsrScopeExclusion]:
    return {entry.table_name: entry for entry in DSR_SCOPE_EXCLUDED_TABLES}


def get_privacy_provider_keys() -> frozenset[str]:
    keys: set[str] = set()
    for entry in PRIVACY_DATA_INVENTORY:
        keys.add(entry.export_provider_key)
        if entry.erasure_provider_key:
            keys.add(entry.erasure_provider_key)
    return frozenset(keys)

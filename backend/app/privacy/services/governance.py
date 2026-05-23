from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    LawfulBasis,
    PrivacyNoticeAcceptance,
    ProcessingPurpose,
    ProcessingPurposeFamily,
    SpecialCategoryCondition,
)
from app.privacy.repositories.privacy_governance import PrivacyGovernanceRepository

_GENERIC_CONSENT_FAMILIES = {
    ProcessingPurposeFamily.MARKETING.value,
    ProcessingPurposeFamily.PRODUCT_ANALYTICS.value,
}
_REGULATED_SERVICE_FAMILIES = {ProcessingPurposeFamily.REGULATED_SERVICE_DELIVERY.value}


class PrivacyGovernanceError(ValueError):
    """Base privacy governance error."""


class PrivacyConfigurationError(PrivacyGovernanceError):
    """Raised when a privacy purpose or authorization is misconfigured."""


class PrivacyProcessingDenied(PrivacyGovernanceError):
    """Raised when processing is not currently permitted for a purpose."""


class PrivacyGovernanceService:
    def __init__(self, session: AsyncSession) -> None:
        self.repository = PrivacyGovernanceRepository(session)
        self.audit_events = AuditEventService(session)

    async def register_processing_purpose(
        self,
        *,
        code: str,
        title: str,
        family: ProcessingPurposeFamily,
        default_lawful_basis: LawfulBasis,
        description: str | None = None,
        is_special_category: bool = False,
        default_special_category_condition: SpecialCategoryCondition | None = None,
        requires_active_consent: bool | None = None,
    ) -> ProcessingPurpose:
        purpose_code = _normalise_code(code)
        existing = await self.repository.get_processing_purpose_by_code(
            code=purpose_code
        )
        if existing is not None:
            raise PrivacyConfigurationError("Processing purpose already exists")

        if is_special_category and default_special_category_condition is None:
            raise PrivacyConfigurationError(
                "Special-category purposes require an Article 9 condition"
            )
        consent_required = (
            default_lawful_basis is LawfulBasis.CONSENT
            if requires_active_consent is None
            else requires_active_consent
        )
        if consent_required and default_lawful_basis is not LawfulBasis.CONSENT:
            raise PrivacyConfigurationError(
                "Only consent-based purposes can require active consent"
            )

        return await self.repository.create_processing_purpose(
            code=purpose_code,
            title=title,
            description=description,
            family=family.value,
            default_lawful_basis=default_lawful_basis.value,
            is_special_category=is_special_category,
            default_special_category_condition=(
                default_special_category_condition.value
                if default_special_category_condition is not None
                else None
            ),
            requires_active_consent=consent_required,
        )

    async def create_processing_authorization(
        self,
        *,
        subject_user_id: UUID,
        purpose_code: str,
        lawful_basis: LawfulBasis | None = None,
        special_category_condition: SpecialCategoryCondition | None = None,
        valid_from: datetime | None = None,
        valid_until: datetime | None = None,
        source: str | None = None,
        consent_source_purpose_code: str | None = None,
    ) -> DataProcessingAuthorization:
        purpose = await self._get_active_purpose(purpose_code)
        effective_lawful_basis = lawful_basis or LawfulBasis(
            purpose.default_lawful_basis
        )
        effective_special_condition = self._resolve_special_category_condition(
            purpose=purpose,
            special_category_condition=special_category_condition,
        )
        if (
            purpose.requires_active_consent
            and effective_lawful_basis is not LawfulBasis.CONSENT
        ):
            raise PrivacyConfigurationError(
                "This purpose requires consent as its lawful basis"
            )
        await self._assert_not_generic_consent_for_regulated_purpose(
            target_purpose=purpose,
            consent_source_purpose_code=consent_source_purpose_code,
        )

        return await self.repository.create_authorization(
            subject_user_id=subject_user_id,
            purpose_id=purpose.id,
            lawful_basis=effective_lawful_basis.value,
            special_category_condition=(
                effective_special_condition.value
                if effective_special_condition is not None
                else None
            ),
            valid_from=valid_from or datetime.now(UTC),
            valid_until=valid_until,
            source=source,
        )

    async def grant_consent(
        self,
        *,
        subject_user_id: UUID,
        purpose_code: str,
        privacy_notice_version: str,
        audit_context: AuditContext,
        granted_at: datetime | None = None,
        special_category_condition: SpecialCategoryCondition | None = None,
        consent_source_purpose_code: str | None = None,
    ) -> ConsentRecord:
        reference_now = granted_at or datetime.now(UTC)
        purpose = await self._get_active_purpose(purpose_code)
        authorization = await self.create_processing_authorization(
            subject_user_id=subject_user_id,
            purpose_code=purpose.code,
            lawful_basis=LawfulBasis.CONSENT,
            special_category_condition=special_category_condition,
            valid_from=reference_now,
            source="consent_record",
            consent_source_purpose_code=consent_source_purpose_code,
        )
        consent = await self.repository.create_consent_record(
            subject_user_id=subject_user_id,
            purpose_id=purpose.id,
            authorization_id=authorization.id,
            privacy_notice_version=privacy_notice_version,
            granted_at=reference_now,
        )
        await self.audit_events.record_event(
            audit_context=audit_context,
            category=AuditCategory.COMPLIANCE,
            action=AuditAction.CONSENT_GRANTED,
            target_type=AuditTargetType.PRIVACY_CONSENT,
            target_id=subject_user_id,
            metadata_json={
                "purpose_code": purpose.code,
                "privacy_notice_version": privacy_notice_version,
            },
        )
        return consent

    async def withdraw_consent(
        self,
        *,
        subject_user_id: UUID,
        purpose_code: str,
        audit_context: AuditContext,
        withdrawal_reason_code: str | None = None,
        withdrawn_at: datetime | None = None,
    ) -> tuple[int, int]:
        reference_now = withdrawn_at or datetime.now(UTC)
        purpose = await self._get_active_purpose(purpose_code)
        result = await self.repository.withdraw_active_consents(
            subject_user_id=subject_user_id,
            purpose_id=purpose.id,
            withdrawn_at=reference_now,
            withdrawal_reason_code=withdrawal_reason_code,
        )
        await self.audit_events.record_event(
            audit_context=audit_context,
            category=AuditCategory.COMPLIANCE,
            action=AuditAction.CONSENT_WITHDRAWN,
            target_type=AuditTargetType.PRIVACY_CONSENT,
            target_id=subject_user_id,
            metadata_json={
                "purpose_code": purpose.code,
                "withdrawal_reason_code": withdrawal_reason_code,
            },
        )
        return result

    async def accept_privacy_notice(
        self,
        *,
        subject_user_id: UUID,
        notice_version: str,
        audit_context: AuditContext,
        accepted_at: datetime | None = None,
        source: str | None = None,
    ) -> PrivacyNoticeAcceptance:
        reference_now = accepted_at or datetime.now(UTC)
        (
            acceptance,
            created,
        ) = await self.repository.get_or_create_privacy_notice_acceptance(
            subject_user_id=subject_user_id,
            notice_version=notice_version,
            accepted_at=reference_now,
            source=source,
        )
        if not created:
            return acceptance

        await self.audit_events.record_event(
            audit_context=audit_context,
            category=AuditCategory.COMPLIANCE,
            action=AuditAction.PRIVACY_NOTICE_ACCEPTED,
            target_type=AuditTargetType.PRIVACY_NOTICE,
            target_id=subject_user_id,
            metadata_json={"notice_version": notice_version},
        )
        return acceptance

    async def assert_processing_allowed(
        self,
        *,
        subject_user_id: UUID,
        purpose_code: str,
        now: datetime | None = None,
    ) -> DataProcessingAuthorization:
        reference_now = now or datetime.now(UTC)
        purpose = await self._get_active_purpose(purpose_code)
        authorizations = await self.repository.list_active_authorizations(
            subject_user_id=subject_user_id,
            purpose_code=purpose.code,
            now=reference_now,
        )
        for authorization in authorizations:
            if authorization.lawful_basis == LawfulBasis.CONSENT.value:
                active_consent = await self.repository.get_active_consent(
                    subject_user_id=subject_user_id,
                    purpose_id=purpose.id,
                )
                if active_consent is not None:
                    return authorization
                continue
            return authorization

        raise PrivacyProcessingDenied(
            f"Processing is not allowed for purpose '{purpose.code}'"
        )

    async def _get_active_purpose(self, purpose_code: str) -> ProcessingPurpose:
        purpose = await self.repository.get_processing_purpose_by_code(
            code=_normalise_code(purpose_code)
        )
        if purpose is None or not purpose.active:
            raise PrivacyConfigurationError("Processing purpose is not configured")
        return purpose

    def _resolve_special_category_condition(
        self,
        *,
        purpose: ProcessingPurpose,
        special_category_condition: SpecialCategoryCondition | None,
    ) -> SpecialCategoryCondition | None:
        if special_category_condition is not None:
            return special_category_condition
        if purpose.default_special_category_condition is not None:
            return SpecialCategoryCondition(purpose.default_special_category_condition)
        if purpose.is_special_category:
            raise PrivacyConfigurationError(
                "Special-category processing requires an Article 9 condition"
            )
        return None

    async def _assert_not_generic_consent_for_regulated_purpose(
        self,
        *,
        target_purpose: ProcessingPurpose,
        consent_source_purpose_code: str | None,
    ) -> None:
        if target_purpose.family not in _REGULATED_SERVICE_FAMILIES:
            return
        if consent_source_purpose_code is None:
            return

        source_purpose = await self.repository.get_processing_purpose_by_code(
            code=_normalise_code(consent_source_purpose_code)
        )
        if source_purpose is None:
            raise PrivacyConfigurationError("Consent source purpose is not configured")
        if source_purpose.family in _GENERIC_CONSENT_FAMILIES:
            raise PrivacyConfigurationError(
                "Regulated-service processing cannot rely on generic marketing "
                "or product analytics consent"
            )


def _normalise_code(code: str) -> str:
    value = code.strip().lower().replace(" ", "_")
    if not value:
        raise PrivacyConfigurationError("Processing purpose code is required")
    return value

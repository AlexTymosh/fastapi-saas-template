from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import select

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditEvent
from app.privacy.models.privacy_governance import (
    DataProcessingAuthorization,
    LawfulBasis,
    PrivacyNoticeAcceptance,
    ProcessingPurposeFamily,
    SpecialCategoryCondition,
)
from app.privacy.services.governance import (
    PrivacyConfigurationError,
    PrivacyGovernanceService,
    PrivacyProcessingDenied,
)
from app.users.models.user import User
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


async def _create_user(session, *, email: str = "subject@example.com") -> User:
    user = User(
        external_auth_id=f"kc|{uuid4()}",
        email=email,
        email_verified=True,
    )
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user


def test_privacy_governance_tracks_distinct_purpose_lawful_bases(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            service = PrivacyGovernanceService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            await service.register_processing_purpose(
                code="marketing",
                title="Marketing communications",
                family=ProcessingPurposeFamily.MARKETING,
                default_lawful_basis=LawfulBasis.CONSENT,
            )
            await service.register_processing_purpose(
                code="audit_retention",
                title="Audit retention",
                family=ProcessingPurposeFamily.LEGAL_COMPLIANCE,
                default_lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
            )
            await service.register_processing_purpose(
                code="regulated_service_delivery",
                title="Regulated service delivery",
                family=ProcessingPurposeFamily.REGULATED_SERVICE_DELIVERY,
                default_lawful_basis=LawfulBasis.PUBLIC_TASK,
                is_special_category=True,
                default_special_category_condition=(
                    SpecialCategoryCondition.REGULATED_SERVICE_PROVISION
                ),
            )

            await service.grant_consent(
                subject_user_id=user.id,
                purpose_code="marketing",
                privacy_notice_version="2026-05",
                audit_context=audit_context,
            )
            await service.create_processing_authorization(
                subject_user_id=user.id,
                purpose_code="audit_retention",
                source="platform_policy",
            )
            await service.create_processing_authorization(
                subject_user_id=user.id,
                purpose_code="regulated_service_delivery",
                source="regulated_service_policy",
            )
            await service.accept_privacy_notice(
                subject_user_id=user.id,
                notice_version="2026-05",
                audit_context=audit_context,
                source="signup",
            )

            stmt = select(DataProcessingAuthorization).where(
                DataProcessingAuthorization.subject_user_id == user.id
            )
            authorizations = list((await session.execute(stmt)).scalars().all())

            assert {item.lawful_basis for item in authorizations} == {
                LawfulBasis.CONSENT.value,
                LawfulBasis.LEGAL_OBLIGATION.value,
                LawfulBasis.PUBLIC_TASK.value,
            }
            regulated_authorization = next(
                item
                for item in authorizations
                if item.lawful_basis == LawfulBasis.PUBLIC_TASK.value
            )
            assert regulated_authorization.special_category_condition == (
                SpecialCategoryCondition.REGULATED_SERVICE_PROVISION.value
            )

            event_actions = set(
                (
                    await session.execute(
                        select(AuditEvent.action).where(AuditEvent.target_id == user.id)
                    )
                )
                .scalars()
                .all()
            )
            assert AuditAction.CONSENT_GRANTED.value in event_actions
            assert AuditAction.PRIVACY_NOTICE_ACCEPTED.value in event_actions

    run_async(_run())


def test_consent_withdrawal_blocks_only_consent_based_processing(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            service = PrivacyGovernanceService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            await service.register_processing_purpose(
                code="marketing",
                title="Marketing communications",
                family=ProcessingPurposeFamily.MARKETING,
                default_lawful_basis=LawfulBasis.CONSENT,
            )
            await service.register_processing_purpose(
                code="audit_retention",
                title="Audit retention",
                family=ProcessingPurposeFamily.LEGAL_COMPLIANCE,
                default_lawful_basis=LawfulBasis.LEGAL_OBLIGATION,
            )
            await service.grant_consent(
                subject_user_id=user.id,
                purpose_code="marketing",
                privacy_notice_version="2026-05",
                audit_context=audit_context,
            )
            await service.create_processing_authorization(
                subject_user_id=user.id,
                purpose_code="audit_retention",
                source="platform_policy",
            )

            await service.assert_processing_allowed(
                subject_user_id=user.id,
                purpose_code="marketing",
            )
            await service.withdraw_consent(
                subject_user_id=user.id,
                purpose_code="marketing",
                audit_context=audit_context,
                withdrawal_reason_code="user_request",
            )

            with pytest.raises(PrivacyProcessingDenied):
                await service.assert_processing_allowed(
                    subject_user_id=user.id,
                    purpose_code="marketing",
                )

            audit_authorization = await service.assert_processing_allowed(
                subject_user_id=user.id,
                purpose_code="audit_retention",
            )
            assert audit_authorization.lawful_basis == (
                LawfulBasis.LEGAL_OBLIGATION.value
            )

            event_actions = set(
                (
                    await session.execute(
                        select(AuditEvent.action).where(AuditEvent.target_id == user.id)
                    )
                )
                .scalars()
                .all()
            )
            assert AuditAction.CONSENT_WITHDRAWN.value in event_actions

    run_async(_run())


def test_special_category_processing_requires_article_9_condition(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            service = PrivacyGovernanceService(session)

            with pytest.raises(PrivacyConfigurationError):
                await service.register_processing_purpose(
                    code="regulated_service_delivery",
                    title="Regulated service delivery",
                    family=ProcessingPurposeFamily.REGULATED_SERVICE_DELIVERY,
                    default_lawful_basis=LawfulBasis.PUBLIC_TASK,
                    is_special_category=True,
                )

    run_async(_run())


def test_regulated_processing_cannot_reuse_generic_marketing_consent(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            service = PrivacyGovernanceService(session)

            await service.register_processing_purpose(
                code="marketing",
                title="Marketing communications",
                family=ProcessingPurposeFamily.MARKETING,
                default_lawful_basis=LawfulBasis.CONSENT,
            )
            await service.register_processing_purpose(
                code="regulated_service_delivery",
                title="Regulated service delivery",
                family=ProcessingPurposeFamily.REGULATED_SERVICE_DELIVERY,
                default_lawful_basis=LawfulBasis.CONSENT,
                is_special_category=True,
                default_special_category_condition=(
                    SpecialCategoryCondition.EXPLICIT_CONSENT
                ),
            )

            with pytest.raises(PrivacyConfigurationError):
                await service.create_processing_authorization(
                    subject_user_id=user.id,
                    purpose_code="regulated_service_delivery",
                    lawful_basis=LawfulBasis.CONSENT,
                    consent_source_purpose_code="marketing",
                )

    run_async(_run())


def test_privacy_notice_acceptance_is_idempotent(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            user = await _create_user(session)
            service = PrivacyGovernanceService(session)
            audit_context = AuditContext(actor_user_id=user.id)

            first = await service.accept_privacy_notice(
                subject_user_id=user.id,
                notice_version="2026-05",
                audit_context=audit_context,
                source="signup",
            )
            second = await service.accept_privacy_notice(
                subject_user_id=user.id,
                notice_version="2026-05",
                audit_context=audit_context,
                source="client_retry",
            )

            assert second.id == first.id
            assert second.source == "signup"

            acceptances = list(
                (
                    await session.execute(
                        select(PrivacyNoticeAcceptance).where(
                            PrivacyNoticeAcceptance.subject_user_id == user.id,
                            PrivacyNoticeAcceptance.notice_version == "2026-05",
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(acceptances) == 1

            notice_events = list(
                (
                    await session.execute(
                        select(AuditEvent).where(
                            AuditEvent.target_id == user.id,
                            AuditEvent.action
                            == AuditAction.PRIVACY_NOTICE_ACCEPTED.value,
                        )
                    )
                )
                .scalars()
                .all()
            )
            assert len(notice_events) == 1

    run_async(_run())

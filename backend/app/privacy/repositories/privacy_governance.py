from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.privacy.models.privacy_governance import (
    ConsentRecord,
    DataProcessingAuthorization,
    PrivacyNoticeAcceptance,
    ProcessingPurpose,
)


class PrivacyGovernanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create_processing_purpose(
        self,
        *,
        code: str,
        title: str,
        description: str | None,
        family: str,
        default_lawful_basis: str,
        is_special_category: bool,
        default_special_category_condition: str | None,
        requires_active_consent: bool,
        active: bool = True,
    ) -> ProcessingPurpose:
        purpose = ProcessingPurpose(
            code=code,
            title=title,
            description=description,
            family=family,
            default_lawful_basis=default_lawful_basis,
            is_special_category=is_special_category,
            default_special_category_condition=default_special_category_condition,
            requires_active_consent=requires_active_consent,
            active=active,
        )
        self.session.add(purpose)
        await self.session.flush()
        await self.session.refresh(purpose)
        return purpose

    async def get_processing_purpose_by_code(
        self,
        *,
        code: str,
    ) -> ProcessingPurpose | None:
        stmt = select(ProcessingPurpose).where(ProcessingPurpose.code == code)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create_authorization(
        self,
        *,
        subject_user_id: UUID,
        purpose_id: UUID,
        lawful_basis: str,
        special_category_condition: str | None,
        valid_from: datetime,
        valid_until: datetime | None,
        source: str | None,
    ) -> DataProcessingAuthorization:
        authorization = DataProcessingAuthorization(
            subject_user_id=subject_user_id,
            purpose_id=purpose_id,
            lawful_basis=lawful_basis,
            special_category_condition=special_category_condition,
            valid_from=valid_from,
            valid_until=valid_until,
            source=source,
        )
        self.session.add(authorization)
        await self.session.flush()
        await self.session.refresh(authorization)
        return authorization

    async def list_active_authorizations(
        self,
        *,
        subject_user_id: UUID,
        purpose_code: str,
        now: datetime,
    ) -> list[DataProcessingAuthorization]:
        stmt = (
            select(DataProcessingAuthorization)
            .join(ProcessingPurpose)
            .where(
                DataProcessingAuthorization.subject_user_id == subject_user_id,
                ProcessingPurpose.code == purpose_code,
                ProcessingPurpose.active.is_(True),
                DataProcessingAuthorization.active.is_(True),
                DataProcessingAuthorization.revoked_at.is_(None),
                DataProcessingAuthorization.valid_from <= now,
                or_(
                    DataProcessingAuthorization.valid_until.is_(None),
                    DataProcessingAuthorization.valid_until > now,
                ),
            )
            .order_by(DataProcessingAuthorization.valid_from.desc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def create_consent_record(
        self,
        *,
        subject_user_id: UUID,
        purpose_id: UUID,
        authorization_id: UUID | None,
        privacy_notice_version: str,
        granted_at: datetime,
    ) -> ConsentRecord:
        record = ConsentRecord(
            subject_user_id=subject_user_id,
            purpose_id=purpose_id,
            authorization_id=authorization_id,
            privacy_notice_version=privacy_notice_version,
            granted_at=granted_at,
        )
        self.session.add(record)
        await self.session.flush()
        await self.session.refresh(record)
        return record

    async def get_active_consent(
        self,
        *,
        subject_user_id: UUID,
        purpose_id: UUID,
    ) -> ConsentRecord | None:
        stmt = (
            select(ConsentRecord)
            .where(
                ConsentRecord.subject_user_id == subject_user_id,
                ConsentRecord.purpose_id == purpose_id,
                ConsentRecord.withdrawn_at.is_(None),
            )
            .order_by(ConsentRecord.granted_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def withdraw_active_consents(
        self,
        *,
        subject_user_id: UUID,
        purpose_id: UUID,
        withdrawn_at: datetime,
        withdrawal_reason_code: str | None,
    ) -> tuple[int, int]:
        consent_result = await self.session.execute(
            update(ConsentRecord)
            .where(
                ConsentRecord.subject_user_id == subject_user_id,
                ConsentRecord.purpose_id == purpose_id,
                ConsentRecord.withdrawn_at.is_(None),
            )
            .values(
                withdrawn_at=withdrawn_at,
                withdrawal_reason_code=withdrawal_reason_code,
            )
            .execution_options(synchronize_session=False)
        )
        authorization_result = await self.session.execute(
            update(DataProcessingAuthorization)
            .where(
                DataProcessingAuthorization.subject_user_id == subject_user_id,
                DataProcessingAuthorization.purpose_id == purpose_id,
                DataProcessingAuthorization.lawful_basis == "consent",
                DataProcessingAuthorization.active.is_(True),
                DataProcessingAuthorization.revoked_at.is_(None),
            )
            .values(active=False, revoked_at=withdrawn_at)
            .execution_options(synchronize_session=False)
        )
        await self.session.flush()
        return int(consent_result.rowcount or 0), int(
            authorization_result.rowcount or 0
        )

    async def create_privacy_notice_acceptance(
        self,
        *,
        subject_user_id: UUID,
        notice_version: str,
        accepted_at: datetime,
        source: str | None,
    ) -> PrivacyNoticeAcceptance:
        acceptance = PrivacyNoticeAcceptance(
            subject_user_id=subject_user_id,
            notice_version=notice_version,
            accepted_at=accepted_at,
            source=source,
        )
        self.session.add(acceptance)
        await self.session.flush()
        await self.session.refresh(acceptance)
        return acceptance

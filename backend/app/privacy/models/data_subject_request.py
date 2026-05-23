from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db.base import Base
from app.core.db.mixins import TimestampMixin, UUIDMixin

class DataSubjectRequestType(StrEnum):
    ACCESS = "access"; EXPORT = "export"; ERASE = "erase"; RECTIFY = "rectify"; RESTRICT = "restrict"; OBJECT = "object"; PORTABILITY = "portability"
class DataSubjectRequestStatus(StrEnum):
    SUBMITTED="submitted"; UNDER_REVIEW="under_review"; APPROVED="approved"; REJECTED="rejected"; FULFILLED="fulfilled"; CANCELLED="cancelled"
_REQ=", ".join(repr(i.value) for i in DataSubjectRequestType)
_ST=", ".join(repr(i.value) for i in DataSubjectRequestStatus)
class DataSubjectRequest(UUIDMixin, TimestampMixin, Base):
    __tablename__='data_subject_requests'
    __table_args__=(CheckConstraint(f"request_type IN ({_REQ})",name='ck_dsr_request_type'),CheckConstraint(f"status IN ({_ST})",name='ck_dsr_status'),Index('ix_dsr_subject_status_created','subject_user_id','status','created_at'),Index('ix_dsr_requester_created','requester_user_id','created_at'),Index('ix_dsr_status_due','status','due_at'),Index('ix_dsr_type_status','request_type','status'),Index('ix_dsr_idempotency_key_hash','idempotency_key_hash'),Index('ix_dsr_idempotency_expires','idempotency_key_expires_at'))
    request_type: Mapped[str]=mapped_column(String(32),nullable=False)
    status: Mapped[str]=mapped_column(String(32),nullable=False,default=DataSubjectRequestStatus.SUBMITTED.value,server_default=sa.text("'submitted'"))
    requester_user_id: Mapped[UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'))
    subject_user_id: Mapped[UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'))
    submitted_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),server_default=sa.text('CURRENT_TIMESTAMP'),nullable=False)
    acknowledged_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); reviewed_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); decided_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); fulfilled_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); cancelled_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    reviewer_user_id: Mapped[UUID|None]=mapped_column(ForeignKey('users.id',ondelete='SET NULL'))
    decision_reason_code: Mapped[str|None]=mapped_column(String(64)); rejection_reason_code: Mapped[str|None]=mapped_column(String(64)); requester_note: Mapped[str|None]=mapped_column(Text); internal_note: Mapped[str|None]=mapped_column(Text)
    due_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),nullable=False)
    extended_until: Mapped[datetime|None]=mapped_column(DateTime(timezone=True)); extension_reason_code: Mapped[str|None]=mapped_column(String(64))
    idempotency_key_hash: Mapped[str|None]=mapped_column(String(128)); idempotency_fingerprint: Mapped[str|None]=mapped_column(String(128)); idempotency_key_expires_at: Mapped[datetime|None]=mapped_column(DateTime(timezone=True))
    export_artifact_id: Mapped[UUID|None]=mapped_column(nullable=True); erasure_job_id: Mapped[UUID|None]=mapped_column(nullable=True)

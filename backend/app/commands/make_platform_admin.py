from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.db import get_session_factory
from app.core.errors.exceptions import AppError, ConflictError, NotFoundError
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import UserStatus
from app.users.repositories.users import UserRepository


class MakePlatformAdminStatus(StrEnum):
    GRANTED = "granted"
    ALREADY_ACTIVE = "already_active"


@dataclass(frozen=True, slots=True)
class MakePlatformAdminResult:
    email: str
    status: MakePlatformAdminStatus


async def make_platform_admin(
    email: str, *, force: bool = False
) -> MakePlatformAdminResult:
    async with get_session_factory()() as session:
        async with session.begin():
            user = await UserRepository(session).get_by_email(email)
            if user is None:
                raise NotFoundError(detail=f"User with email {email} not found")
            if user.status != UserStatus.ACTIVE:
                raise ConflictError(detail="User is not active")

            repo = PlatformStaffRepository(session)
            existing = await repo.get_by_user_id(user.id)
            audit_action = AuditAction.PLATFORM_STAFF_CREATED
            audit_metadata: dict[str, object] | None = None
            if existing is not None:
                if (
                    existing.role == PlatformStaffRole.PLATFORM_ADMIN.value
                    and existing.status == PlatformStaffStatus.ACTIVE.value
                ):
                    return MakePlatformAdminResult(
                        email=email,
                        status=MakePlatformAdminStatus.ALREADY_ACTIVE,
                    )
                if not force:
                    raise ConflictError(
                        detail=(
                            "Platform staff record exists; use --force to promote "
                            "the existing record to platform_admin"
                        )
                    )
                audit_action = AuditAction.PLATFORM_STAFF_ROLE_CHANGED
                audit_metadata = {
                    "old_role": existing.role,
                    "new_role": PlatformStaffRole.PLATFORM_ADMIN.value,
                }
                staff = await repo.promote_to_active_platform_admin(staff=existing)
            else:
                staff = await repo.create_staff(
                    user_id=user.id,
                    role=PlatformStaffRole.PLATFORM_ADMIN.value,
                )

            await AuditEventService(session).record_event(
                audit_context=AuditContext(actor_user_id=None),
                category=AuditCategory.PLATFORM,
                action=audit_action,
                target_type=AuditTargetType.PLATFORM_STAFF,
                target_id=staff.id,
                reason="bootstrap platform admin",
                metadata_json=audit_metadata,
            )
            return MakePlatformAdminResult(
                email=email,
                status=MakePlatformAdminStatus.GRANTED,
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grant platform_admin to an existing active local user."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Promote an existing platform_staff record to active platform_admin.",
    )
    return parser


async def _amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = await make_platform_admin(args.email, force=args.force)
    except AppError as exc:
        print(exc.detail or exc.title, file=sys.stderr)
        return 1
    except (RuntimeError, SQLAlchemyError) as exc:
        print(f"Failed to make platform admin: {exc}", file=sys.stderr)
        return 2

    if result.status == MakePlatformAdminStatus.ALREADY_ACTIVE:
        print(f"User {result.email} is already an active platform admin")
    else:
        print(f"Platform admin granted to {result.email}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())

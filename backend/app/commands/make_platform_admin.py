from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum

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


async def make_platform_admin(email: str) -> MakePlatformAdminResult:
    async with get_session_factory()() as session:
        async with session.begin():
            user = await UserRepository(session).get_by_email(email)
            if user is None:
                raise NotFoundError(detail=f"User with email {email} not found")
            if user.status == UserStatus.SUSPENDED:
                raise ConflictError(detail=f"User {email} is suspended")

            repo = PlatformStaffRepository(session)
            existing = await repo.get_by_user_id(user.id)
            if existing is not None:
                if (
                    existing.role == PlatformStaffRole.PLATFORM_ADMIN.value
                    and existing.status == PlatformStaffStatus.ACTIVE.value
                ):
                    return MakePlatformAdminResult(
                        email=email,
                        status=MakePlatformAdminStatus.ALREADY_ACTIVE,
                    )
                raise ConflictError(
                    detail=(
                        "Platform staff record already exists with a non-active "
                        "platform_admin state; manage it explicitly"
                    )
                )

            staff = await repo.create_staff(
                user_id=user.id,
                role=PlatformStaffRole.PLATFORM_ADMIN.value,
            )
            await AuditEventService(session).record_event(
                audit_context=AuditContext(actor_user_id=None),
                category=AuditCategory.PLATFORM,
                action=AuditAction.PLATFORM_STAFF_CREATED,
                target_type=AuditTargetType.PLATFORM_STAFF,
                target_id=staff.id,
                reason="bootstrap platform admin",
            )
            return MakePlatformAdminResult(
                email=email,
                status=MakePlatformAdminStatus.GRANTED,
            )


def _message_for_result(result: MakePlatformAdminResult) -> str:
    if result.status == MakePlatformAdminStatus.ALREADY_ACTIVE:
        return f"User {result.email} is already an active platform admin"
    return f"Platform admin granted to {result.email}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grant platform_admin to an existing active local user."
    )
    parser.add_argument("--email", required=True)
    return parser


async def _run_cli(email: str) -> int:
    result = await make_platform_admin(email)
    print(_message_for_result(result))
    return 0


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    try:
        return asyncio.run(_run_cli(args.email))
    except AppError as exc:
        print(exc.detail or exc.title, file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Unexpected error while granting platform admin: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

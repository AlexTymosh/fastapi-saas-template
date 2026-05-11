from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.config.settings import get_settings
from app.core.db import get_session_factory
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User, UserStatus
from app.users.repositories.users import UserRepository

LOCAL_USER_NOT_FOUND_MESSAGE = (
    "Local user not found. The target admin must log in once before platform bootstrap."
)


class PlatformAdminBootstrapStatus(StrEnum):
    CREATED_STAFF = "created_staff"
    PROMOTED_STAFF = "promoted_staff"
    ALREADY_PLATFORM_ADMIN = "already_platform_admin"


@dataclass(frozen=True, slots=True)
class PlatformAdminBootstrapResult:
    target_user_id: UUID
    platform_staff_id: UUID
    status: PlatformAdminBootstrapStatus
    previous_role: str | None
    previous_status: str | None
    new_role: str
    new_status: str
    email: str


class PlatformAdminBootstrapService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        environment_provider: Callable[[], str] | None = None,
    ) -> None:
        self.session_factory = session_factory or get_session_factory()
        self.environment_provider = environment_provider or (
            lambda: get_settings().app.environment
        )

    async def bootstrap_platform_admin_by_email(
        self,
        *,
        email: str,
        reason: str,
        external_auth_id: str | None = None,
        confirm_production: bool = False,
        restore_suspended_staff: bool = False,
    ) -> PlatformAdminBootstrapResult:
        normalised_email = self._normalise_email(email)
        normalised_external_auth_id = self._normalise_external_auth_id(external_auth_id)
        normalised_reason = reason.strip()
        if not normalised_reason:
            raise ConflictError(detail="Bootstrap reason is required")
        if self.environment_provider() == "prod" and not confirm_production:
            raise ConflictError(
                detail=("Production platform bootstrap requires --confirm-production.")
            )

        async with self.session_factory() as session:
            async with session.begin():
                user = await self._select_user(
                    session=session,
                    email=normalised_email,
                    external_auth_id=normalised_external_auth_id,
                )
                self._validate_user(user)

                staff_repository = PlatformStaffRepository(session)
                staff = await staff_repository.get_by_user_id(user.id)
                previous_role = staff.role if staff is not None else None
                previous_status = staff.status if staff is not None else None

                if staff is None:
                    staff = await staff_repository.create_staff(
                        user_id=user.id,
                        role=PlatformStaffRole.PLATFORM_ADMIN.value,
                        created_by_user_id=None,
                    )
                    result_status = PlatformAdminBootstrapStatus.CREATED_STAFF
                elif (
                    staff.role == PlatformStaffRole.PLATFORM_ADMIN.value
                    and staff.status == PlatformStaffStatus.ACTIVE.value
                ):
                    result_status = PlatformAdminBootstrapStatus.ALREADY_PLATFORM_ADMIN
                else:
                    if (
                        staff.status == PlatformStaffStatus.SUSPENDED.value
                        and not restore_suspended_staff
                    ):
                        raise ConflictError(
                            detail=(
                                "Platform staff is suspended. Re-run with "
                                "--restore-suspended-staff to restore and promote."
                            )
                        )
                    staff = await staff_repository.promote_to_active_platform_admin(
                        staff=staff
                    )
                    result_status = PlatformAdminBootstrapStatus.PROMOTED_STAFF

                await AuditEventService(session).record_event(
                    audit_context=AuditContext(
                        actor_user_id=None,
                        ip_address=None,
                        user_agent="platform-bootstrap-cli",
                    ),
                    category=AuditCategory.PLATFORM,
                    action=AuditAction.PLATFORM_ADMIN_BOOTSTRAPPED,
                    target_type=AuditTargetType.PLATFORM_STAFF,
                    target_id=staff.id,
                    reason=normalised_reason,
                    metadata_json={
                        "actor_type": "system",
                        "command": "platform_admin_bootstrap",
                        "bootstrap_result": result_status.value,
                        "target_user_id": str(user.id),
                        "target_email": normalised_email,
                        "previous_role": previous_role,
                        "new_role": staff.role,
                        "previous_status": previous_status,
                        "new_status": staff.status,
                    },
                )
                return PlatformAdminBootstrapResult(
                    target_user_id=user.id,
                    platform_staff_id=staff.id,
                    status=result_status,
                    previous_role=previous_role,
                    previous_status=previous_status,
                    new_role=staff.role,
                    new_status=staff.status,
                    email=normalised_email,
                )

    async def _select_user(
        self,
        *,
        session: AsyncSession,
        email: str,
        external_auth_id: str | None,
    ) -> User:
        user_repository = UserRepository(session)
        users = await user_repository.list_by_normalized_email(email)
        if not users:
            raise NotFoundError(detail=LOCAL_USER_NOT_FOUND_MESSAGE)
        if external_auth_id is None:
            if len(users) > 1:
                raise ConflictError(
                    detail=(
                        "Multiple local users match the email. Re-run with "
                        "--external-auth-id to disambiguate."
                    )
                )
            return users[0]

        matched_users = [
            user for user in users if user.external_auth_id == external_auth_id
        ]
        if len(matched_users) != 1:
            raise ConflictError(
                detail=(
                    "--external-auth-id does not uniquely match a local user "
                    "for the email."
                )
            )
        return matched_users[0]

    def _validate_user(self, user: User) -> None:
        if user.status != UserStatus.ACTIVE:
            raise ConflictError(detail="User is suspended")
        if not user.email_verified:
            raise ConflictError(detail="User email is not verified")

    def _normalise_email(self, email: str) -> str:
        normalised_email = email.strip().lower()
        if not normalised_email:
            raise ConflictError(detail="Bootstrap email is required")
        return normalised_email

    def _normalise_external_auth_id(self, external_auth_id: str | None) -> str | None:
        if external_auth_id is None:
            return None
        normalised = external_auth_id.strip()
        return normalised or None

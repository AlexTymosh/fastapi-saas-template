from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit.context import AuditContext
from app.audit.models.audit_event import AuditAction, AuditCategory, AuditTargetType
from app.audit.services.audit_events import AuditEventService
from app.core.errors.exceptions import ConflictError, NotFoundError
from app.platform.models.platform_staff import PlatformStaffRole, PlatformStaffStatus
from app.platform.repositories.platform_staff import PlatformStaffRepository
from app.users.models.user import User, UserStatus
from app.users.repositories.users import UserRepository


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
    target_email: str


class PlatformAdminBootstrapService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        environment: str = "local",
    ) -> None:
        self.session_factory = session_factory
        self.environment = environment

    async def bootstrap_platform_admin_by_email(
        self,
        *,
        email: str,
        reason: str,
        external_auth_id: str | None = None,
        confirm_production: bool = False,
        restore_suspended_staff: bool = False,
    ) -> PlatformAdminBootstrapResult:
        normalized_email = self._normalize_email(email)
        normalized_reason = reason.strip()
        normalized_external_auth_id = self._normalize_optional(external_auth_id)
        self._validate_request(
            normalized_email=normalized_email,
            reason=normalized_reason,
            confirm_production=confirm_production,
        )

        async with self.session_factory() as session:
            async with session.begin():
                users = await UserRepository(session).list_by_normalized_email(
                    normalized_email
                )
                user = self._select_user(
                    users=users,
                    external_auth_id=normalized_external_auth_id,
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
                                "Platform staff is suspended; rerun with "
                                "--restore-suspended-staff to restore and promote it."
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
                    reason=normalized_reason,
                    metadata_json=self._audit_metadata(
                        result_status=result_status,
                        user=user,
                        normalized_email=normalized_email,
                        previous_role=previous_role,
                        previous_status=previous_status,
                        new_role=staff.role,
                        new_status=staff.status,
                    ),
                )

                return PlatformAdminBootstrapResult(
                    target_user_id=user.id,
                    platform_staff_id=staff.id,
                    status=result_status,
                    previous_role=previous_role,
                    previous_status=previous_status,
                    new_role=staff.role,
                    new_status=staff.status,
                    target_email=normalized_email,
                )

    def _validate_request(
        self,
        *,
        normalized_email: str,
        reason: str,
        confirm_production: bool,
    ) -> None:
        if not normalized_email:
            raise ConflictError(detail="Email is required")
        if not reason:
            raise ConflictError(detail="Bootstrap reason is required")
        if self.environment == "prod" and not confirm_production:
            raise ConflictError(
                detail="Production bootstrap requires --confirm-production"
            )

    def _select_user(
        self,
        *,
        users: list[User],
        external_auth_id: str | None,
    ) -> User:
        if not users:
            raise NotFoundError(
                detail=(
                    "Local user not found. The target admin must log in once before "
                    "platform bootstrap."
                )
            )
        if external_auth_id is not None:
            matching_users = [
                user for user in users if user.external_auth_id == external_auth_id
            ]
            if len(matching_users) == 1:
                return matching_users[0]
            raise ConflictError(
                detail="External auth ID does not uniquely identify an email match"
            )
        if len(users) > 1:
            raise ConflictError(
                detail=(
                    "Multiple local users match this email; rerun with "
                    "--external-auth-id to disambiguate."
                )
            )
        return users[0]

    def _validate_user(self, user: User) -> None:
        if user.status != UserStatus.ACTIVE:
            raise ConflictError(detail="User is not active")
        if not user.email_verified:
            raise ConflictError(detail="User email is not verified")

    def _audit_metadata(
        self,
        *,
        result_status: PlatformAdminBootstrapStatus,
        user: User,
        normalized_email: str,
        previous_role: str | None,
        previous_status: str | None,
        new_role: str,
        new_status: str,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {
            "actor_type": "system",
            "command": "platform_admin_bootstrap",
            "bootstrap_result": result_status.value,
            "target_user_id": str(user.id),
            "target_email": normalized_email,
            "new_role": new_role,
            "new_status": new_status,
        }
        if previous_role is not None:
            metadata["previous_role"] = previous_role
        if previous_status is not None:
            metadata["previous_status"] = previous_status
        return metadata

    def _normalize_email(self, email: str) -> str:
        return email.strip().lower()

    def _normalize_optional(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

from __future__ import annotations

from enum import StrEnum

from app.platform.models.platform_staff import PlatformStaffRole

PlatformRole = PlatformStaffRole


class PlatformPermission(StrEnum):
    USERS_READ = "users:read"
    USERS_READ_LIMITED = "users:read_limited"
    USERS_SUSPEND = "users:suspend"
    USERS_RESTORE = "users:restore"
    USERS_CORRECT_PROFILE = "users:correct_profile"
    ORGANISATIONS_READ = "organisations:read"
    ORGANISATIONS_READ_LIMITED = "organisations:read_limited"
    ORGANISATIONS_SUSPEND = "organisations:suspend"
    ORGANISATIONS_RESTORE = "organisations:restore"
    ORGANISATIONS_CORRECT_PROFILE = "organisations:correct_profile"
    ORGANISATIONS_EMERGENCY_OWNER_CORRECTION = (
        "organisations:emergency_owner_correction"
    )
    PLATFORM_STAFF_MANAGE = "platform_staff:manage"
    AUDIT_READ = "audit:read"
    AUDIT_READ_LIMITED = "audit:read_limited"
    GDPR_EXPORT = "gdpr:export"
    GDPR_ERASE = "gdpr:erase"


ALL_PERMISSIONS = frozenset(PlatformPermission)
ROLE_PERMISSIONS = {
    PlatformRole.PLATFORM_ADMIN: ALL_PERMISSIONS,
    PlatformRole.SUPPORT_AGENT: frozenset(
        {
            PlatformPermission.USERS_READ_LIMITED,
            PlatformPermission.ORGANISATIONS_READ_LIMITED,
            PlatformPermission.AUDIT_READ_LIMITED,
        }
    ),
    PlatformRole.COMPLIANCE_OFFICER: frozenset(
        {
            PlatformPermission.USERS_READ_LIMITED,
            PlatformPermission.ORGANISATIONS_READ_LIMITED,
            PlatformPermission.AUDIT_READ,
            PlatformPermission.AUDIT_READ_LIMITED,
            PlatformPermission.GDPR_EXPORT,
            PlatformPermission.GDPR_ERASE,
        }
    ),
}

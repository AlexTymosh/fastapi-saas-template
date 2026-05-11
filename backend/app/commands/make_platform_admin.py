from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError

from app.core.errors.exceptions import AppError
from app.platform.services.platform_bootstrap import (
    PlatformAdminBootstrapService,
    PlatformAdminBootstrapStatus,
)


class MakePlatformAdminStatus(StrEnum):
    GRANTED = "granted"
    ALREADY_ACTIVE = "already_active"


@dataclass(frozen=True, slots=True)
class MakePlatformAdminResult:
    email: str
    status: MakePlatformAdminStatus


async def make_platform_admin(
    email: str,
    *,
    force: bool = False,
    reason: str = "bootstrap platform admin",
    external_auth_id: str | None = None,
    confirm_production: bool = False,
) -> MakePlatformAdminResult:
    result = await PlatformAdminBootstrapService().bootstrap_platform_admin_by_email(
        email=email,
        reason=reason,
        external_auth_id=external_auth_id,
        confirm_production=confirm_production,
        restore_suspended_staff=force,
    )
    status = (
        MakePlatformAdminStatus.ALREADY_ACTIVE
        if result.status == PlatformAdminBootstrapStatus.ALREADY_PLATFORM_ADMIN
        else MakePlatformAdminStatus.GRANTED
    )
    return MakePlatformAdminResult(email=result.email, status=status)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Grant platform_admin to an existing active local user."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--reason",
        default="bootstrap platform admin",
        help="Audit reason for the offline platform admin bootstrap.",
    )
    parser.add_argument(
        "--external-auth-id",
        help="Optional Keycloak subject for disambiguating duplicate local emails.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Restore a suspended platform_staff record before promotion.",
    )
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required when APP__ENVIRONMENT=prod.",
    )
    return parser


async def _amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = await make_platform_admin(
            args.email,
            force=args.force,
            reason=args.reason,
            external_auth_id=args.external_auth_id,
            confirm_production=args.confirm_production,
        )
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

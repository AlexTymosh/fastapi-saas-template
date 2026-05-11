from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import get_settings
from app.core.db import get_session_factory
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
    email: str, *, force: bool = False
) -> MakePlatformAdminResult:
    settings = get_settings()
    result = await PlatformAdminBootstrapService(
        get_session_factory(), environment=settings.app.environment
    ).bootstrap_platform_admin_by_email(
        email=email,
        reason="bootstrap platform admin",
        confirm_production=settings.app.environment != "prod",
        restore_suspended_staff=force,
    )
    status = (
        MakePlatformAdminStatus.ALREADY_ACTIVE
        if result.status == PlatformAdminBootstrapStatus.ALREADY_PLATFORM_ADMIN
        else MakePlatformAdminStatus.GRANTED
    )
    return MakePlatformAdminResult(email=result.target_email, status=status)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Legacy alias. Prefer: python -m app.platform.cli.bootstrap_admin "
            "--email admin@example.com --reason 'Initial platform admin bootstrap'"
        )
    )
    parser.add_argument("--email", required=True)
    parser.add_argument(
        "--force",
        action="store_true",
        help="Restore a suspended platform_staff record while promoting it.",
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

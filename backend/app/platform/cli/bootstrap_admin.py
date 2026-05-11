from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy.exc import SQLAlchemyError

from app.core.config.settings import get_settings
from app.core.db import get_session_factory
from app.core.errors.exceptions import AppError
from app.platform.services.platform_bootstrap import PlatformAdminBootstrapService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Safely bootstrap platform_admin for an existing local user."
    )
    parser.add_argument("--email", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--external-auth-id")
    parser.add_argument(
        "--confirm-production",
        action="store_true",
        help="Required when APP__ENVIRONMENT=prod.",
    )
    parser.add_argument(
        "--restore-suspended-staff",
        action="store_true",
        help="Restore a suspended platform_staff row while promoting it to admin.",
    )
    return parser


async def _amain(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    service = PlatformAdminBootstrapService(
        get_session_factory(),
        environment=settings.app.environment,
    )
    try:
        result = await service.bootstrap_platform_admin_by_email(
            email=args.email,
            reason=args.reason,
            external_auth_id=args.external_auth_id,
            confirm_production=args.confirm_production,
            restore_suspended_staff=args.restore_suspended_staff,
        )
    except AppError as exc:
        print(exc.detail or exc.title, file=sys.stderr)
        return 1
    except (RuntimeError, SQLAlchemyError) as exc:
        print(f"Failed to bootstrap platform admin: {exc}", file=sys.stderr)
        return 2

    print(
        "Platform admin bootstrap succeeded: "
        f"result={result.status.value}, "
        f"email={result.target_email}, "
        f"user_id={result.target_user_id}, "
        f"staff_id={result.platform_staff_id}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(argv))


if __name__ == "__main__":
    raise SystemExit(main())

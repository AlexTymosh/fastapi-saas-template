from __future__ import annotations

import argparse
import asyncio
import logging

from app.core.db.session import dispose_engine, get_session_factory
from app.privacy.maintenance import expire_ready_export_artifacts

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Expire ready privacy export artifacts and purge their stored "
            "archive objects."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show how many artifacts would be expired without changing data "
            "or deleting storage objects."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Maximum number of expired ready artifacts to process in one run.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout output. The command still emits structured logs.",
    )
    return parser


async def run_once(*, dry_run: bool = False, batch_size: int = 1000) -> int:
    if batch_size < 1:
        raise ValueError("Privacy export retention batch size must be positive")

    session_factory = get_session_factory()
    async with session_factory() as session:
        expired_count = await expire_ready_export_artifacts(
            session,
            dry_run=dry_run,
            limit=batch_size,
        )
        if dry_run:
            await session.rollback()
        else:
            await session.commit()
    return expired_count


async def _amain(*, quiet: bool, dry_run: bool, batch_size: int) -> int:
    try:
        expired_count = await run_once(
            dry_run=dry_run,
            batch_size=batch_size,
        )
        action = "would expire" if dry_run else "expired"
        logger.info(
            "Privacy export retention %s %s artifact(s)",
            action,
            expired_count,
        )
        if not quiet:
            print(f"Privacy export retention {action} {expired_count} artifact(s)")
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return asyncio.run(
        _amain(
            quiet=args.quiet,
            dry_run=args.dry_run,
            batch_size=args.batch_size,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

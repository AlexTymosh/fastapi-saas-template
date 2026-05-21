from __future__ import annotations

import argparse
import asyncio
import logging

from app.audit.maintenance import anonymise_expired_audit_events
from app.core.config.settings import get_settings
from app.core.db.session import dispose_engine, get_session_factory

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Anonymise expired audit events according to AUDIT__* retention settings."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many audit events would be anonymised without changing data.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout output. The command still emits structured logs.",
    )
    return parser


async def run_once(*, dry_run: bool = False) -> int:
    settings = get_settings()
    session_factory = get_session_factory()

    async with session_factory() as session:
        anonymised_count = await anonymise_expired_audit_events(
            session,
            settings=settings.audit,
        )
        if dry_run:
            await session.rollback()
        else:
            await session.commit()

    return anonymised_count


async def _amain(*, quiet: bool, dry_run: bool) -> int:
    try:
        anonymised_count = await run_once(dry_run=dry_run)
        action = "would anonymise" if dry_run else "anonymised"
        logger.info(
            "Audit retention %s %s expired event(s)",
            action,
            anonymised_count,
        )
        if not quiet:
            print(f"Audit retention {action} {anonymised_count} expired event(s)")
        return 0
    finally:
        await dispose_engine()


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    return asyncio.run(_amain(quiet=args.quiet, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())

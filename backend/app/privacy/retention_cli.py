from __future__ import annotations

import argparse
import asyncio
import logging

from app.core.db.session import dispose_engine, get_session_factory
from app.privacy.maintenance import run_privacy_retention_pass

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run one privacy retention pass across export artifacts, invites, "
            "outbox payloads, audit events, and expired DSR idempotency keys."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Show how many rows/objects would be retained without changing data "
            "or deleting storage objects."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1000,
        help="Maximum rows/objects to process per retention step in one run.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout output. The command still emits structured logs.",
    )
    return parser


async def run_once(*, dry_run: bool = False, batch_size: int = 1000) -> dict[str, int]:
    if batch_size < 1:
        raise ValueError("Privacy retention batch size must be positive")

    session_factory = get_session_factory()
    summary = await run_privacy_retention_pass(
        session_factory,
        dry_run=dry_run,
        limit=batch_size,
    )
    return summary.as_log_extra()


async def _amain(*, quiet: bool, dry_run: bool, batch_size: int) -> int:
    try:
        summary = await run_once(
            dry_run=dry_run,
            batch_size=batch_size,
        )
        action = "would retain" if dry_run else "retained"
        logger.info("Privacy retention %s rows/objects", action, extra=summary)
        if not quiet:
            print(_format_summary(action=action, summary=summary))
        return 0
    finally:
        await dispose_engine()


def _format_summary(*, action: str, summary: dict[str, int]) -> str:
    details = ", ".join(
        f"{key}={value}" for key, value in summary.items() if key != "total"
    )
    return f"Privacy retention {action} {summary['total']} total ({details})"


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

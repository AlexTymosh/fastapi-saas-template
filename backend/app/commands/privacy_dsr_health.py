from __future__ import annotations

import argparse
import asyncio
import logging
import selectors
import sys
from datetime import timedelta

from app.core.config.settings import get_settings
from app.core.db.session import dispose_engine, get_session_factory
from app.core.observability import init_observability, shutdown_observability

logger = logging.getLogger(__name__)

DEFAULT_DSR_STALE_AFTER_SECONDS = 3600


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Print one DSR execution health snapshot for operators.",
    )
    parser.add_argument(
        "--stale-after-seconds",
        type=int,
        default=DEFAULT_DSR_STALE_AFTER_SECONDS,
        help="Seconds after which queued/processing DSR jobs are treated as stale.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress stdout output. The command still emits structured logs.",
    )
    return parser


async def run_once(*, stale_after_seconds: int) -> dict[str, object]:
    if stale_after_seconds < 1:
        raise ValueError("DSR execution stale_after_seconds must be positive")

    from app.privacy.services.dsr_execution_health import (
        get_privacy_dsr_execution_health,
    )

    session_factory = get_session_factory()
    async with session_factory() as session:
        snapshot = await get_privacy_dsr_execution_health(
            session,
            stale_after=timedelta(seconds=stale_after_seconds),
        )
    return snapshot.as_log_extra()


async def _amain(*, quiet: bool, stale_after_seconds: int) -> int:
    observability_started = False
    try:
        await init_observability(get_settings())
        observability_started = True

        summary = await run_once(stale_after_seconds=stale_after_seconds)
        logger.info("Privacy DSR execution health checked", extra=summary)
        if not quiet:
            print(_format_summary(summary))
        return 0
    finally:
        if observability_started:
            await shutdown_observability()
        await dispose_engine()


def _format_summary(summary: dict[str, object]) -> str:
    fields = (
        "status",
        "total_dsr_jobs",
        "failed_dsr_jobs",
        "stale_dsr_jobs",
        "failed_export_artifacts",
        "stale_export_artifacts",
    )
    details = " ".join(f"{field}={summary[field]}" for field in fields)
    return f"Privacy DSR execution health {details}"


def _run_async_cli(awaitable) -> int:
    if sys.platform == "win32":
        return asyncio.run(
            awaitable,
            loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()),
        )
    return asyncio.run(awaitable)


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return _run_async_cli(
        _amain(
            quiet=args.quiet,
            stale_after_seconds=args.stale_after_seconds,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())

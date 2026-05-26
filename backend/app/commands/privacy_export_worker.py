from __future__ import annotations

import argparse
import asyncio

from app.core.db.session import get_session_factory
from app.privacy.services.export_artifacts import ExportArtifactService


async def run_worker(*, batch_size: int, dry_run: bool, once: bool) -> int:
    total_processed = 0

    while True:
        session_factory = get_session_factory()
        async with session_factory() as session:
            async with session.begin():
                service = ExportArtifactService(session)
                if dry_run:
                    processed_this_iteration = await service.count_queued_artifacts(
                        limit=batch_size
                    )
                else:
                    processed_this_iteration = (
                        await service.claim_and_generate_next_batch(
                            batch_size=batch_size
                        )
                    )
                total_processed += processed_this_iteration

        if once or processed_this_iteration == 0:
            break

    print(
        "privacy_export_worker "
        f"processed={total_processed} dry_run={dry_run} once={once}"
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Privacy export artifact worker")
    parser.add_argument("--batch-size", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    return asyncio.run(
        run_worker(batch_size=args.batch_size, dry_run=args.dry_run, once=args.once)
    )


if __name__ == "__main__":
    raise SystemExit(main())

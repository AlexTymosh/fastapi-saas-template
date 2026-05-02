from __future__ import annotations

from app.core.tasks import configure_broker


def bootstrap_worker_runtime() -> None:
    """Initialise runtime dependencies required for Dramatiq worker startup."""

    configure_broker(require_redis=True)


bootstrap_worker_runtime()

# Ensure actors are imported and registered after broker bootstrap.
from app.outbox.workers import process_outbox_event  # noqa: E402,F401

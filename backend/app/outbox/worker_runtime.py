from __future__ import annotations

from app.core.tasks import configure_broker


def bootstrap_worker_runtime() -> None:
    """Initialise mandatory runtime dependencies for Dramatiq workers."""

    configure_broker(require_redis=True)


bootstrap_worker_runtime()

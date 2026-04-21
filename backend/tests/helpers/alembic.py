from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


class AlembicUpgradeError(RuntimeError):
    """Raised when Alembic migration setup fails for test databases."""


def upgrade_database_to_head(database_url: str) -> None:
    """Run Alembic migrations to head for the provided database URL."""
    backend_root = Path(__file__).resolve().parents[2]

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_root,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    if result.returncode != 0:
        raise AlembicUpgradeError(
            "alembic upgrade head failed "
            f"(database_url={database_url!r}, returncode={result.returncode})\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

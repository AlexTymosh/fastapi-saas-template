from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def upgrade_database_to_head(database_url: str) -> None:
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
        raise RuntimeError(
            "Failed to upgrade test database to Alembic head.\n"
            f"Command: {sys.executable} -m alembic upgrade head\n"
            f"Working directory: {backend_root}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

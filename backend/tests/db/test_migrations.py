from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _run_alembic(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_alembic_upgrade_head_and_check(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/migrations.db"
    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    check = _run_alembic("check", env=env)
    assert check.returncode == 0, check.stdout + "\n" + check.stderr


def test_alembic_downgrade_and_reupgrade_head(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/migrations-cycle.db"
    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    downgrade = _run_alembic("downgrade", "base", env=env)
    assert downgrade.returncode == 0, downgrade.stdout + "\n" + downgrade.stderr

    reupgrade = _run_alembic("upgrade", "head", env=env)
    assert reupgrade.returncode == 0, reupgrade.stdout + "\n" + reupgrade.stderr

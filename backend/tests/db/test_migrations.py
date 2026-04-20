from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

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


def _is_safe_external_test_database_url(database_url: str) -> bool:
    normalized = database_url.lower()
    local_markers = ("localhost", "127.0.0.1", "0.0.0.0")
    test_markers = ("test", "pytest", "ci")
    return any(marker in normalized for marker in local_markers) and any(
        marker in normalized for marker in test_markers
    )


@pytest.mark.integration
def test_alembic_upgrade_head_check_and_downgrade_base(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/migrations.db"

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    check = _run_alembic("check", env=env)
    assert check.returncode == 0, check.stdout + "\n" + check.stderr

    downgrade = _run_alembic("downgrade", "base", env=env)
    assert downgrade.returncode == 0, downgrade.stdout + "\n" + downgrade.stderr

    upgrade_again = _run_alembic("upgrade", "head", env=env)
    assert upgrade_again.returncode == 0, (
        upgrade_again.stdout + "\n" + upgrade_again.stderr
    )


@pytest.mark.integration
def test_alembic_upgrade_head_and_check_with_external_database() -> None:
    if os.getenv("RUN_EXTERNAL_DB_MIGRATION_TESTS") != "1":
        pytest.skip("Set RUN_EXTERNAL_DB_MIGRATION_TESTS=1 to run external DB migrations")

    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if not _is_safe_external_test_database_url(database_url):
        pytest.skip(
            "TEST_DATABASE_URL must target an explicitly local test database "
            "(localhost/127.0.0.1 and include test marker)"
        )

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    check = _run_alembic("check", env=env)
    assert check.returncode == 0, check.stdout + "\n" + check.stderr

    downgrade = _run_alembic("downgrade", "base", env=env)
    assert downgrade.returncode == 0, downgrade.stdout + "\n" + downgrade.stderr

    upgrade_again = _run_alembic("upgrade", "head", env=env)
    assert upgrade_again.returncode == 0, (
        upgrade_again.stdout + "\n" + upgrade_again.stderr
    )

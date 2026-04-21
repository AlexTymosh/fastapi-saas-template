from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

import pytest
import sqlalchemy as sa

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


def _is_safe_test_database_url(database_url: str) -> bool:
    """
    Guardrail for optional external migration validation.

    Accept only clearly test-scoped URLs by default:
    - local hostnames (localhost / 127.0.0.1)
    - db name/path contains one of: test, ci, tmp
    """
    parsed = urlparse(database_url)
    if parsed.scheme.startswith("sqlite"):
        return True

    host = (parsed.hostname or "").lower()
    db_name_or_path = (parsed.path or "").lower()
    markers = ("test", "ci", "tmp")
    has_test_marker = any(marker in db_name_or_path for marker in markers)
    is_local_host = host in {"localhost", "127.0.0.1"}
    return is_local_host and has_test_marker


@pytest.mark.integration
def test_alembic_upgrade_head_check_and_downgrade_base(tmp_path) -> None:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/migrations.db"

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    engine = sa.create_engine(f"sqlite:///{tmp_path}/migrations.db")
    with engine.connect() as connection:
        inspector = sa.inspect(connection)
        unique_constraints = {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("users")
        }
        membership_indexes = {
            index["name"] for index in inspector.get_indexes("memberships")
        }
        invite_columns = {column["name"] for column in inspector.get_columns("invites")}
        membership_role_checks = inspector.get_check_constraints("memberships")

    assert "uq_users_external_auth_id" in unique_constraints
    assert "uq_users_email" not in unique_constraints
    assert "uq_memberships_user_id_active" in membership_indexes
    assert "expires_at" in invite_columns
    assert any(
        "admin" in (constraint.get("sqltext") or "")
        for constraint in membership_role_checks
    )

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
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not set")
    if os.getenv("ENABLE_EXTERNAL_MIGRATION_DB_TEST") != "1":
        pytest.skip(
            "Set ENABLE_EXTERNAL_MIGRATION_DB_TEST=1 to run external DB migration test"
        )
    if not _is_safe_test_database_url(database_url):
        pytest.skip(
            "TEST_DATABASE_URL must point to a clearly test-scoped local database"
        )

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    check = _run_alembic("check", env=env)
    assert check.returncode == 0, check.stdout + "\n" + check.stderr

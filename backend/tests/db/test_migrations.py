from __future__ import annotations

import os
import re
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
    allowed_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "host.docker.internal",
        "docker.for.mac.localhost",
        "docker.for.win.localhost",
    }
    if host not in allowed_hosts:
        return False

    db_name_or_path = (parsed.path or "").lower().lstrip("/")
    markers = ("test", "ci", "tmp")
    has_test_marker = any(marker in db_name_or_path for marker in markers)
    if not has_test_marker:
        return False

    blocked_database_names = {"app", "postgres", "prod", "production", "main"}
    db_name_tokens = set(filter(None, re.split(r"[^a-z0-9]+", db_name_or_path)))
    return blocked_database_names.isdisjoint(db_name_tokens)


@pytest.mark.integration
def test_alembic_upgrade_head_check_and_downgrade_base(
    postgres_integration_url: str,
) -> None:
    database_url = postgres_integration_url

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    engine = sa.create_engine(database_url)
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

    assert "uq_users_external_auth_id" in unique_constraints
    assert "uq_users_email" not in unique_constraints
    assert "uq_memberships_user_id_active" in membership_indexes
    assert "expires_at" in invite_columns
    # PostgreSQL reflection differs slightly across SQLAlchemy/Alembic versions.
    # This migration contract asserts only stable guarantees.

    check = _run_alembic("check", env=env)
    assert check.returncode == 0, check.stdout + "\n" + check.stderr

    downgrade = _run_alembic("downgrade", "base", env=env)
    assert downgrade.returncode == 0, downgrade.stdout + "\n" + downgrade.stderr

    upgrade_again = _run_alembic("upgrade", "head", env=env)
    assert upgrade_again.returncode == 0, (
        upgrade_again.stdout + "\n" + upgrade_again.stderr
    )


@pytest.mark.integration
@pytest.mark.external_db
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


@pytest.mark.unit
@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("sqlite+aiosqlite:///./tmp.db", True),
        ("postgresql://user:pass@localhost:5432/app_test", True),
        ("postgresql://user:pass@127.0.0.1:5432/ci_database", True),
        ("postgresql://user:pass@host.docker.internal:5432/my_tmp_db", True),
        ("postgresql://user:pass@db.internal:5432/app_test", False),
        ("postgresql://user:pass@localhost:5432/postgres_test", False),
        ("postgresql://user:pass@localhost:5432/production_tmp", False),
        ("postgresql://user:pass@localhost:5432/app", False),
        ("postgresql://user:pass@localhost:5432/myapp", False),
    ],
)
def test_is_safe_test_database_url(database_url: str, expected: bool) -> None:
    assert _is_safe_test_database_url(database_url) is expected

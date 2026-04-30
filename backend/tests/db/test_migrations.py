from __future__ import annotations

import os
import re
import subprocess
import sys
import time
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

    db_name_or_path = (parsed.path or "").lower().strip("/")
    db_name_tokens = set(filter(None, re.split(r"[^a-z0-9]+", db_name_or_path)))

    required_markers = {"test", "ci", "tmp"}
    has_required_marker = not required_markers.isdisjoint(db_name_tokens) or any(
        marker in db_name_or_path for marker in required_markers
    )
    if not has_required_marker:
        return False

    blocked_exact_names = {"app", "postgres", "prod", "production", "main"}
    if db_name_or_path in blocked_exact_names:
        return False

    blocked_tokens = {"postgres", "prod", "production", "main"}
    return blocked_tokens.isdisjoint(db_name_tokens)


def _is_external_database_reachable(database_url: str) -> bool:
    parsed = urlparse(database_url)
    connect_args: dict[str, int] = {}
    if parsed.scheme.startswith("postgresql") and "psycopg" in parsed.scheme:
        connect_args = {"connect_timeout": 2}

    engine = sa.create_engine(database_url, connect_args=connect_args)
    try:
        with engine.connect() as connection:
            connection.execute(sa.text("SELECT 1"))
        return True
    except (sa.exc.OperationalError, sa.exc.DBAPIError):
        return False
    finally:
        engine.dispose()


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
    if not _is_external_database_reachable(database_url):
        pytest.skip("External test database is not reachable")

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    check = _run_alembic("check", env=env)
    assert check.returncode == 0, check.stdout + "\n" + check.stderr


@pytest.mark.integration
def test_invite_pending_email_uniqueness_index_contract(
    postgres_integration_url: str,
) -> None:
    database_url = postgres_integration_url

    env = os.environ.copy()
    env["DATABASE__URL"] = database_url

    upgrade = _run_alembic("upgrade", "head", env=env)
    assert upgrade.returncode == 0, upgrade.stdout + "\n" + upgrade.stderr

    engine = sa.create_engine(database_url)
    try:
        with engine.begin() as connection:
            organisation_id = connection.execute(
                sa.text(
                    """
                    INSERT INTO organisations (id, name, slug, status)
                    VALUES (gen_random_uuid(), :name, :slug, 'active')
                    RETURNING id
                    """
                ),
                {"name": "Migration Org", "slug": "migration-org"},
            ).scalar_one()

            connection.execute(
                sa.text(
                    """
                    INSERT INTO invites (
                        id, email, organisation_id, role, status, token_hash
                    )
                    VALUES (
                        gen_random_uuid(), :email, :organisation_id,
                        'member', 'pending', :token_hash
                    )
                    """
                ),
                {
                    "email": "Test@Example.com",
                    "organisation_id": organisation_id,
                    "token_hash": "hash-1",
                },
            )

            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(
                    sa.text(
                        """
                        INSERT INTO invites (
                        id, email, organisation_id, role, status, token_hash
                    )
                        VALUES (
                        gen_random_uuid(), :email, :organisation_id,
                        'member', 'pending', :token_hash
                    )
                        """
                    ),
                    {
                        "email": "test@example.com",
                        "organisation_id": organisation_id,
                        "token_hash": "hash-2",
                    },
                )

            connection.execute(
                sa.text(
                    """
                    UPDATE invites
                    SET status = 'revoked'
                    WHERE organisation_id = :organisation_id
                    AND lower(email) = lower(:email)
                    """
                ),
                {"organisation_id": organisation_id, "email": "test@example.com"},
            )

            connection.execute(
                sa.text(
                    """
                    INSERT INTO invites (
                        id, email, organisation_id, role, status, token_hash
                    )
                    VALUES (
                        gen_random_uuid(), :email, :organisation_id,
                        'member', 'pending', :token_hash
                    )
                    """
                ),
                {
                    "email": "test@example.com",
                    "organisation_id": organisation_id,
                    "token_hash": "hash-3",
                },
            )
    finally:
        engine.dispose()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("database_url", "expected"),
    [
        ("sqlite+aiosqlite:///./tmp.db", True),
        ("postgresql://user:pass@localhost:5432/app_test", True),
        ("postgresql://user:pass@127.0.0.1:5432/ci_database", True),
        ("postgresql://user:pass@host.docker.internal:5432/my_tmp_db", True),
        ("postgresql://user:pass@[::1]:5432/test_db", True),
        ("postgresql://user:pass@db.internal:5432/app_test", False),
        ("postgresql://user:pass@example.com:5432/app_test", False),
        ("postgresql://user:pass@localhost:5432/postgres", False),
        ("postgresql://user:pass@localhost:5432/main", False),
        ("postgresql://user:pass@localhost:5432/prod", False),
        ("postgresql://user:pass@localhost:5432/production", False),
        ("postgresql://user:pass@localhost:5432/postgres_test", False),
        ("postgresql://user:pass@localhost:5432/main_test", False),
        ("postgresql://user:pass@localhost:5432/prod_test", False),
        ("postgresql://user:pass@localhost:5432/production_tmp", False),
        ("postgresql://user:pass@localhost:5432/app", False),
        ("postgresql://user:pass@localhost:5432/myapp", False),
        ("postgresql://user:pass@localhost:5432/service", False),
    ],
)
def test_is_safe_test_database_url(database_url: str, expected: bool) -> None:
    assert _is_safe_test_database_url(database_url) is expected


@pytest.mark.unit
def test_is_external_database_reachable_returns_false_fast_for_unreachable_port() -> (
    None
):
    start = time.monotonic()
    reachable = _is_external_database_reachable(
        "postgresql+psycopg://postgres:postgres@127.0.0.1:1/app_test"
    )
    elapsed = time.monotonic() - start

    assert reachable is False
    assert elapsed < 5


@pytest.mark.unit
def test_safe_url_check_rejects_unsafe_url() -> None:
    assert (
        _is_safe_test_database_url("postgresql://user:pass@localhost:5432/production")
        is False
    )


@pytest.mark.unit
def test_external_db_test_keeps_opt_in_marker() -> None:
    external_db_test = test_alembic_upgrade_head_and_check_with_external_database
    marker_names = {marker.name for marker in external_db_test.pytestmark}
    assert "external_db" in marker_names


@pytest.mark.unit
def test_external_db_test_requires_enable_env_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "TEST_DATABASE_URL", "postgresql://user:pass@localhost:5432/app_test"
    )
    monkeypatch.delenv("ENABLE_EXTERNAL_MIGRATION_DB_TEST", raising=False)

    with pytest.raises(
        pytest.skip.Exception,
        match=(
            "Set ENABLE_EXTERNAL_MIGRATION_DB_TEST=1 to run external DB migration test"
        ),
    ):
        test_alembic_upgrade_head_and_check_with_external_database()

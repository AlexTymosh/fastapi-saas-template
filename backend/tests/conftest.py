from __future__ import annotations

import pytest

from tests.fixtures.app import client as client
from tests.fixtures.app import client_factory as client_factory
from tests.fixtures.auth import (
    authenticated_client_factory as authenticated_client_factory,
)
from tests.fixtures.db import migrated_database_url as migrated_database_url
from tests.fixtures.db import migrated_session_factory as migrated_session_factory
from tests.fixtures.settings import reset_runtime_state as reset_runtime_state

__all__ = [
    "authenticated_client_factory",
    "client",
    "client_factory",
    "migrated_database_url",
    "migrated_session_factory",
    "reset_runtime_state",
]


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--run-external-db",
        action="store_true",
        default=False,
        help=(
            "Run opt-in tests that use TEST_DATABASE_URL against a persistent "
            "external test database."
        ),
    )


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if config.getoption("--run-external-db"):
        return

    skip_external_db = pytest.mark.skip(
        reason="external_db tests require explicit --run-external-db"
    )
    for item in items:
        if "external_db" in item.keywords:
            item.add_marker(skip_external_db)

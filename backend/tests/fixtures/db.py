from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from tests.helpers.alembic import upgrade_database_to_head
from tests.helpers.asyncio_runner import run_async


@pytest.fixture
def migrated_database_url(tmp_path) -> str:
    database_url = f"sqlite+aiosqlite:///{tmp_path}/migrated.db"
    upgrade_database_to_head(database_url)
    return database_url


@pytest.fixture
def migrated_session_factory(migrated_database_url: str):
    engine = create_async_engine(migrated_database_url)
    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    yield session_factory
    run_async(engine.dispose())

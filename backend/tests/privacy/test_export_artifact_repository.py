from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.privacy.models.export_artifact import ExportArtifact
from app.privacy.repositories.export_artifacts import ExportArtifactRepository
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


class _StatementCaptureSession:
    def __init__(self, dialect_name: str) -> None:
        self.statement = None
        self.refreshed = None

        class _Bind:
            class dialect:
                name = dialect_name

        self.bind = _Bind()

    async def execute(self, statement):
        self.statement = statement

        class _Result:
            def scalars(self):
                return self

            def all(self):
                return []

        return _Result()

    async def flush(self):
        return None

    async def refresh(self, instance):
        self.refreshed = instance
        return None


def test_claim_queued_batch_uses_skip_locked_for_non_sqlite() -> None:
    async def _run() -> None:
        session = _StatementCaptureSession("postgresql")
        repository = ExportArtifactRepository(session)  # type: ignore[arg-type]

        await repository.claim_queued_batch(limit=10, lease_seconds=300)

        assert session.statement is not None
        compiled = str(session.statement.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE SKIP LOCKED" in compiled

    run_async(_run())


def test_increment_download_count_uses_atomic_update_statement() -> None:
    async def _run() -> None:
        session = _StatementCaptureSession("postgresql")
        repository = ExportArtifactRepository(session)  # type: ignore[arg-type]
        artifact = ExportArtifact(id=uuid4(), download_count=0)

        await repository.increment_download_count(artifact)

        assert session.statement is not None
        compiled = str(session.statement.compile(dialect=postgresql.dialect()))
        compact_sql = " ".join(compiled.split())
        compact_no_spaces = compiled.replace(" ", "")
        assert compact_sql.startswith("UPDATE export_artifacts SET")
        assert "download_count=(export_artifacts.download_count+" in compact_no_spaces
        assert "downloaded_at=" in compact_no_spaces
        assert session.refreshed is artifact

    run_async(_run())

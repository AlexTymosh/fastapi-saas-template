from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql

from app.privacy.repositories.export_artifacts import ExportArtifactRepository
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy]


class _StatementCaptureSession:
    def __init__(self, dialect_name: str) -> None:
        self.statement = None

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


def test_claim_queued_batch_uses_skip_locked_for_non_sqlite() -> None:
    async def _run() -> None:
        session = _StatementCaptureSession("postgresql")
        repository = ExportArtifactRepository(session)  # type: ignore[arg-type]

        await repository.claim_queued_batch(10)

        assert session.statement is not None
        compiled = str(session.statement.compile(dialect=postgresql.dialect()))
        assert "FOR UPDATE SKIP LOCKED" in compiled

    run_async(_run())

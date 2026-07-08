from __future__ import annotations

from datetime import timedelta

import pytest

from app.commands import privacy_dsr_health
from app.privacy.services import dsr_execution_health
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


class _FakeSnapshot:
    def as_log_extra(self) -> dict[str, object]:
        return {
            "status": "ok",
            "total_dsr_jobs": 0,
            "failed_dsr_jobs": 0,
            "stale_dsr_jobs": 0,
            "failed_export_artifacts": 0,
            "stale_export_artifacts": 0,
        }


class _FakeTransaction:
    def __init__(self, session: _FakeSession, order: list[str]) -> None:
        self.session = session
        self.order = order

    async def __aenter__(self) -> _FakeTransaction:
        self.order.append("transaction_enter")
        self.session.in_transaction = True
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        del exc, traceback
        outcome = "rollback" if exc_type is not None else "commit"
        self.order.append(f"transaction_exit:{outcome}")
        self.session.in_transaction = False
        return False


class _FakeSession:
    def __init__(self, order: list[str]) -> None:
        self.order = order
        self.in_transaction = False

    def begin(self) -> _FakeTransaction:
        self.order.append("transaction_begin")
        return _FakeTransaction(self, self.order)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession, order: list[str]) -> None:
        self.session = session
        self.order = order

    async def __aenter__(self) -> _FakeSession:
        self.order.append("session_enter")
        return self.session

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        del exc_type, exc, traceback
        self.order.append("session_exit")
        return False


class _FakeSessionFactory:
    def __init__(self, session: _FakeSession, order: list[str]) -> None:
        self.session = session
        self.order = order

    def __call__(self) -> _FakeSessionContext:
        self.order.append("session_factory_call")
        return _FakeSessionContext(self.session, self.order)


def test_privacy_dsr_health_cli_owns_transaction_boundary(monkeypatch) -> None:
    order: list[str] = []
    fake_session = _FakeSession(order)

    async def _get_privacy_dsr_execution_health(session, *, stale_after):
        assert session is fake_session
        assert stale_after == timedelta(seconds=60)
        assert fake_session.in_transaction
        order.append("snapshot")
        return _FakeSnapshot()

    monkeypatch.setattr(
        privacy_dsr_health,
        "get_session_factory",
        lambda: _FakeSessionFactory(fake_session, order),
    )
    monkeypatch.setattr(
        dsr_execution_health,
        "get_privacy_dsr_execution_health",
        _get_privacy_dsr_execution_health,
    )

    async def _run() -> None:
        summary = await privacy_dsr_health.run_once(stale_after_seconds=60)

        assert summary["status"] == "ok"
        assert order == [
            "session_factory_call",
            "session_enter",
            "transaction_begin",
            "transaction_enter",
            "snapshot",
            "transaction_exit:commit",
            "session_exit",
        ]

    run_async(_run())


def test_privacy_dsr_health_cli_transaction_rolls_back_on_snapshot_failure(
    monkeypatch,
) -> None:
    order: list[str] = []
    fake_session = _FakeSession(order)

    class SnapshotFailure(RuntimeError):
        pass

    async def _get_privacy_dsr_execution_health(session, *, stale_after):
        assert session is fake_session
        assert stale_after == timedelta(seconds=60)
        assert fake_session.in_transaction
        order.append("snapshot")
        raise SnapshotFailure("snapshot failed")

    monkeypatch.setattr(
        privacy_dsr_health,
        "get_session_factory",
        lambda: _FakeSessionFactory(fake_session, order),
    )
    monkeypatch.setattr(
        dsr_execution_health,
        "get_privacy_dsr_execution_health",
        _get_privacy_dsr_execution_health,
    )

    async def _run() -> None:
        with pytest.raises(SnapshotFailure):
            await privacy_dsr_health.run_once(stale_after_seconds=60)

        assert order == [
            "session_factory_call",
            "session_enter",
            "transaction_begin",
            "transaction_enter",
            "snapshot",
            "transaction_exit:rollback",
            "session_exit",
        ]

    run_async(_run())

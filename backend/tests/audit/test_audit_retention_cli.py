from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

import pytest

from app.audit import retention_cli

pytestmark = [pytest.mark.security]


def test_retention_cli_parser_accepts_quiet_and_dry_run() -> None:
    args = retention_cli.build_parser().parse_args(["--quiet", "--dry-run"])

    assert args.quiet is True
    assert args.dry_run is True


def test_retention_cli_main_passes_quiet_and_dry_run(monkeypatch) -> None:
    captured: dict[str, bool] = {}

    async def _fake_amain(*, quiet: bool, dry_run: bool) -> int:
        captured["quiet"] = quiet
        captured["dry_run"] = dry_run
        return 0

    monkeypatch.setattr(sys, "argv", ["retention_cli", "--quiet", "--dry-run"])
    monkeypatch.setattr(retention_cli, "_amain", _fake_amain)

    assert retention_cli.main() == 0
    assert captured == {"quiet": True, "dry_run": True}


@pytest.mark.parametrize(
    ("dry_run", "expected_commit", "expected_rollback"),
    [
        (False, True, False),
        (True, False, True),
    ],
)
def test_retention_cli_run_once_commits_or_rolls_back(
    dry_run: bool,
    expected_commit: bool,
    expected_rollback: bool,
    monkeypatch,
) -> None:
    audit_settings = object()
    fake_session = _FakeSession()

    async def _fake_anonymise_expired_audit_events(
        session: _FakeSession,
        *,
        settings: object,
    ) -> int:
        assert session is fake_session
        assert settings is audit_settings
        return 7

    monkeypatch.setattr(
        retention_cli,
        "get_settings",
        lambda: SimpleNamespace(audit=audit_settings),
    )
    monkeypatch.setattr(
        retention_cli, "get_session_factory", lambda: fake_session.build
    )
    monkeypatch.setattr(
        retention_cli,
        "anonymise_expired_audit_events",
        _fake_anonymise_expired_audit_events,
    )

    count = asyncio.run(retention_cli.run_once(dry_run=dry_run))

    assert count == 7
    assert fake_session.commit_called is expected_commit
    assert fake_session.rollback_called is expected_rollback


class _FakeSession:
    def __init__(self) -> None:
        self.commit_called = False
        self.rollback_called = False

    def build(self) -> _FakeSession:
        return self

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        return None

    async def commit(self) -> None:
        self.commit_called = True

    async def rollback(self) -> None:
        self.rollback_called = True

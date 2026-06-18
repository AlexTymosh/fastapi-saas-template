from __future__ import annotations

import sys
from pathlib import Path

from app.commands import privacy_export_worker
from tests.helpers.asyncio_runner import run_async


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_worker_dry_run_smoke_does_not_require_storage(monkeypatch) -> None:
    calls: list[int] = []

    async def _count_queued_artifacts(*, batch_size: int) -> int:
        calls.append(batch_size)
        return 0

    monkeypatch.setattr(
        "app.commands.privacy_export_worker._count_queued_artifacts",
        _count_queued_artifacts,
    )

    exit_code = run_async(
        privacy_export_worker.run_worker(
            batch_size=3,
            dry_run=True,
            once=False,
            poll_interval=5,
        )
    )

    assert exit_code == 0
    assert calls == [3]


def test_worker_main_accepts_poll_interval(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def _run_worker(**kwargs: object) -> int:
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(privacy_export_worker, "run_worker", _run_worker)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "privacy_export_worker",
            "--dry-run",
            "--once",
            "--batch-size",
            "2",
            "--poll-interval",
            "1.5",
        ],
    )

    assert privacy_export_worker.main() == 0
    assert captured == {
        "batch_size": 2,
        "dry_run": True,
        "once": True,
        "poll_interval": 1.5,
    }


def test_taskfile_exposes_privacy_export_worker_commands() -> None:
    taskfile = (_repo_root() / "Taskfile.yml").read_text(encoding="utf-8")

    assert "privacy:export-worker:once:" in taskfile
    assert "privacy:export-worker:dry-run:" in taskfile
    assert "python -m app.commands.privacy_export_worker --once" in taskfile
    assert "--dry-run --once" in taskfile


def test_compose_registers_profile_gated_privacy_export_worker() -> None:
    compose = (_repo_root() / "compose.yaml").read_text(encoding="utf-8")

    assert "privacy-export-worker:" in compose
    assert "container_name: fastapi_privacy_export_worker" in compose
    assert "- privacy-exports" in compose
    assert "python -m app.commands.privacy_export_worker" in compose
    assert (
        "--poll-interval ${PRIVACY_EXPORT_WORKER_POLL_INTERVAL_SECONDS:-5}" in compose
    )
    assert "--batch-size ${PRIVACY_EXPORT_WORKER_BATCH_SIZE:-10}" in compose


def test_privacy_export_artifact_docs_include_worker_ops() -> None:
    docs = (_repo_root() / "backend/docs/privacy-export-artifacts.md").read_text(
        encoding="utf-8"
    )

    assert "## Worker operations" in docs
    assert "task privacy:export-worker:once" in docs
    assert "task privacy:export-worker:dry-run" in docs
    assert "docker compose --profile privacy-exports" in docs

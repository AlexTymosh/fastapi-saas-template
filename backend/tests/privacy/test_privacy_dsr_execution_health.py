from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from app.commands import privacy_dsr_health
from app.core.observability import privacy_dsr_metrics
from app.privacy.models.data_subject_request import (
    DataSubjectRequest,
    DataSubjectRequestExecutionStatus,
    DataSubjectRequestStatus,
    DataSubjectRequestType,
)
from app.privacy.models.export_artifact import (
    ExportArtifact,
    ExportArtifactFormat,
    ExportArtifactStatus,
    ExportArtifactStorageBackend,
)
from app.privacy.services import dsr_execution_health
from app.privacy.services.dsr_execution_health import (
    get_privacy_dsr_execution_health,
)
from tests.helpers.asyncio_runner import run_async

pytestmark = [pytest.mark.privacy, pytest.mark.security]


class _FakeCounter:
    def __init__(self) -> None:
        self.calls: list[tuple[int, dict[str, str]]] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        self.calls.append((value, attributes))


async def _create_dsr(
    session,
    *,
    request_type: DataSubjectRequestType,
    execution_status: DataSubjectRequestExecutionStatus,
    now: datetime,
    old: datetime,
) -> DataSubjectRequest:
    is_active = execution_status in {
        DataSubjectRequestExecutionStatus.QUEUED,
        DataSubjectRequestExecutionStatus.PROCESSING,
    }
    dsr = DataSubjectRequest(
        request_type=request_type.value,
        status=DataSubjectRequestStatus.APPROVED.value,
        execution_status=execution_status.value,
        submitted_at=old,
        due_at=now + timedelta(days=10),
        execution_started_at=old if is_active else None,
        execution_failed_at=(
            old
            if execution_status is DataSubjectRequestExecutionStatus.FAILED
            else None
        ),
        created_at=old,
        updated_at=old,
    )
    session.add(dsr)
    await session.flush()
    return dsr


async def _create_export_artifact(
    session,
    *,
    dsr: DataSubjectRequest,
    status: ExportArtifactStatus,
    now: datetime,
    old: datetime,
) -> ExportArtifact:
    artifact = ExportArtifact(
        data_subject_request_id=dsr.id,
        status=status.value,
        format=ExportArtifactFormat.JSON_ZIP.value,
        storage_backend=ExportArtifactStorageBackend.LOCAL.value,
        schema_version="1.0",
        queued_at=old,
        started_at=old if status is ExportArtifactStatus.PROCESSING else None,
        processing_token=(
            str(uuid4()) if status is ExportArtifactStatus.PROCESSING else None
        ),
        processing_lease_expires_at=(
            now - timedelta(minutes=1)
            if status is ExportArtifactStatus.PROCESSING
            else None
        ),
        failed_at=old if status is ExportArtifactStatus.FAILED else None,
        expires_at=now + timedelta(days=1),
    )
    session.add(artifact)
    await session.flush()
    return artifact


def test_privacy_dsr_execution_health_reports_failed_and_stale_jobs(
    migrated_session_factory,
    monkeypatch,
) -> None:
    captured_points = {}
    captured_logs = []

    def _record_snapshot(*, status, points):
        captured_points["status"] = status
        captured_points["points"] = tuple(points)

    class _FakeLogger:
        def info(self, event_name: str, **kwargs: object) -> None:
            captured_logs.append(("info", event_name, kwargs))

        def warning(self, event_name: str, **kwargs: object) -> None:
            captured_logs.append(("warning", event_name, kwargs))

    monkeypatch.setattr(
        dsr_execution_health,
        "record_privacy_dsr_health_snapshot",
        _record_snapshot,
    )
    monkeypatch.setattr(dsr_execution_health, "log", _FakeLogger())

    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            old = now - timedelta(hours=2)
            failed_export_dsr = await _create_dsr(
                session,
                request_type=DataSubjectRequestType.EXPORT,
                execution_status=DataSubjectRequestExecutionStatus.FAILED,
                now=now,
                old=old,
            )
            await _create_dsr(
                session,
                request_type=DataSubjectRequestType.ERASE,
                execution_status=DataSubjectRequestExecutionStatus.PROCESSING,
                now=now,
                old=old,
            )
            await _create_dsr(
                session,
                request_type=DataSubjectRequestType.EXPORT,
                execution_status=DataSubjectRequestExecutionStatus.QUEUED,
                now=now,
                old=now - timedelta(minutes=5),
            )
            await _create_export_artifact(
                session,
                dsr=failed_export_dsr,
                status=ExportArtifactStatus.FAILED,
                now=now,
                old=old,
            )
            await _create_export_artifact(
                session,
                dsr=failed_export_dsr,
                status=ExportArtifactStatus.PROCESSING,
                now=now,
                old=old,
            )

            snapshot = await get_privacy_dsr_execution_health(
                session,
                now=now,
                stale_after=timedelta(hours=1),
            )

            assert snapshot.status == "degraded"
            assert snapshot.total_dsr_jobs == 3
            assert snapshot.total_failed_dsr_jobs == 1
            assert snapshot.total_stale_dsr_jobs == 1
            assert snapshot.failed_export_artifacts == 1
            assert snapshot.stale_export_artifacts == 1
            assert captured_points["status"] == "degraded"
            assert captured_points["points"]
            assert captured_logs[0][0] == "warning"
            assert captured_logs[0][1] == "privacy_dsr_execution_health_checked"
            assert "requester_user_id" not in str(captured_logs[0][2])
            assert "subject_user_id" not in str(captured_logs[0][2])

    run_async(_run())


def test_privacy_dsr_execution_health_reports_ok_when_no_problem_jobs(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            now = datetime.now(UTC)
            recent = now - timedelta(minutes=5)
            await _create_dsr(
                session,
                request_type=DataSubjectRequestType.EXPORT,
                execution_status=DataSubjectRequestExecutionStatus.DELIVERED,
                now=now,
                old=recent,
            )
            await _create_dsr(
                session,
                request_type=DataSubjectRequestType.ERASE,
                execution_status=DataSubjectRequestExecutionStatus.READY,
                now=now,
                old=recent,
            )

            snapshot = await get_privacy_dsr_execution_health(
                session,
                now=now,
                stale_after=timedelta(hours=1),
                emit_metrics=False,
                emit_log=False,
            )

            assert snapshot.status == "ok"
            assert snapshot.total_failed_dsr_jobs == 0
            assert snapshot.total_stale_dsr_jobs == 0
            assert snapshot.failed_export_artifacts == 0
            assert snapshot.stale_export_artifacts == 0

    run_async(_run())


def test_privacy_dsr_health_metrics_use_low_cardinality_attributes(
    monkeypatch,
) -> None:
    counter = _FakeCounter()
    monkeypatch.setattr(
        privacy_dsr_metrics,
        "privacy_dsr_health_checks_total",
        counter,
    )
    privacy_dsr_metrics._last_privacy_dsr_job_points.clear()  # noqa: SLF001

    point = privacy_dsr_metrics.PrivacyDsrMetricPoint(
        job_kind="dsr_request",
        request_type="export",
        execution_status="failed",
        signal="failed",
        count=2,
    )

    privacy_dsr_metrics.record_privacy_dsr_health_snapshot(
        status="degraded",
        points=[point],
    )

    observations = list(
        privacy_dsr_metrics._observe_privacy_dsr_jobs(None)  # noqa: SLF001
    )
    assert counter.calls == [
        (
            1,
            {privacy_dsr_metrics.PRIVACY_DSR_ATTRIBUTE_HEALTH_STATUS: "degraded"},
        )
    ]
    assert len(observations) == 1
    assert set(observations[0].attributes).issubset(
        privacy_dsr_metrics.ALLOWED_PRIVACY_DSR_JOB_ATTRIBUTE_KEYS
    )
    assert "request_id" not in observations[0].attributes
    assert "user_id" not in observations[0].attributes


def test_privacy_dsr_health_rejects_invalid_stale_threshold(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            with pytest.raises(ValueError, match="stale_after must be positive"):
                await get_privacy_dsr_execution_health(
                    session,
                    stale_after=timedelta(seconds=0),
                )

    run_async(_run())


def test_privacy_dsr_health_cli_uses_selector_loop_factory_on_windows(
    monkeypatch,
) -> None:
    captured_kwargs: dict[str, object] = {}

    async def _noop() -> int:
        return 0

    def _fake_asyncio_run(awaitable, **kwargs):
        captured_kwargs.update(kwargs)
        awaitable.close()
        return 0

    monkeypatch.setattr(privacy_dsr_health.asyncio, "run", _fake_asyncio_run)
    monkeypatch.setattr(privacy_dsr_health.sys, "platform", "win32")

    assert privacy_dsr_health._run_async_cli(_noop()) == 0  # noqa: SLF001
    loop_factory = captured_kwargs["loop_factory"]
    loop = loop_factory()
    try:
        assert isinstance(loop, privacy_dsr_health.asyncio.SelectorEventLoop)
    finally:
        loop.close()

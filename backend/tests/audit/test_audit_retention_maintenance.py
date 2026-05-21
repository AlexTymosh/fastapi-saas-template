from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.audit.maintenance import _normalise_utc


def test_audit_retention_rejects_naive_reference_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _normalise_utc(datetime(2025, 1, 1, 12, 0, 0))


def test_audit_retention_normalises_reference_time_to_utc() -> None:
    source_timezone = timezone(timedelta(hours=2))
    source_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=source_timezone)

    result = _normalise_utc(source_time)

    assert result == datetime(2025, 1, 1, 10, 0, 0, tzinfo=UTC)

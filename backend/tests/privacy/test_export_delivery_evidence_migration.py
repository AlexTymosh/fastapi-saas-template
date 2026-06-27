from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [pytest.mark.privacy]


def _migration_source() -> str:
    backend_root = Path(__file__).resolve().parents[2]
    migration_path = (
        backend_root
        / "migrations"
        / "versions"
        / "0015_separate_export_delivery_evidence.py"
    )
    return migration_path.read_text(encoding="utf-8")


def test_legacy_url_delivery_migration_reclassifies_expired_latest_artifacts():
    source = _migration_source()

    assert "_RESET_READY_LEGACY_URL_DELIVERIES" in source
    assert "_RESET_EXPIRED_LEGACY_URL_DELIVERIES" in source
    assert "latest.status = 'ready'" in source
    assert "latest.status = 'expired'" in source
    assert "execution_status = 'failed'" in source
    assert "execution_failure_reason_code = 'artifact_expired'" in source
    assert "newer.queued_at > latest.queued_at" in source

from __future__ import annotations

from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]


def test_platform_user_service_does_not_query_user_table_directly() -> None:
    source = (_BACKEND_ROOT / "app/platform/services/platform_users.py").read_text()

    assert "from sqlalchemy import func" not in source
    assert "from sqlalchemy import select" not in source
    assert "select(User" not in source
    assert ".get(User" not in source


def test_platform_organisation_service_does_not_query_organisation_table_directly() -> (
    None
):
    source = (
        _BACKEND_ROOT / "app/platform/services/platform_organisations.py"
    ).read_text()

    assert "from sqlalchemy import func" not in source
    assert "from sqlalchemy import select" not in source
    assert "select(Organisation" not in source
    assert ".get(Organisation" not in source

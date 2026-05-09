from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_platform_user_service_uses_domain_repository_for_user_persistence() -> None:
    source = (ROOT / "app/platform/services/platform_users.py").read_text()

    assert "from sqlalchemy import func" not in source
    assert "from sqlalchemy import select" not in source
    assert "session.get(User" not in source
    assert "select(User" not in source
    assert "UserRepository" in source


def test_platform_organisation_service_uses_domain_repository_for_persistence() -> None:
    source = (ROOT / "app/platform/services/platform_organisations.py").read_text()

    assert "from sqlalchemy import func" not in source
    assert "from sqlalchemy import select" not in source
    assert "session.get(Organisation" not in source
    assert "select(Organisation" not in source
    assert "OrganisationRepository" in source

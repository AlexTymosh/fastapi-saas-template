from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("relative_path", "repository_name", "forbidden_snippets"),
    [
        (
            "app/platform/services/platform_users.py",
            "UserRepository",
            [
                "session.execute(",
                "self.session.execute(",
                "select(User",
                "session.get(User",
                "self.session.get(User",
                "from sqlalchemy import select",
                "from sqlalchemy import func",
            ],
        ),
        (
            "app/platform/services/platform_organisations.py",
            "OrganisationRepository",
            [
                "session.execute(",
                "self.session.execute(",
                "select(Organisation",
                "session.get(Organisation",
                "self.session.get(Organisation",
                "from sqlalchemy import select",
                "from sqlalchemy import func",
            ],
        ),
    ],
)
def test_platform_services_use_domain_repositories_for_domain_persistence(
    relative_path: str, repository_name: str, forbidden_snippets: list[str]
) -> None:
    source = (ROOT / relative_path).read_text()

    for snippet in forbidden_snippets:
        assert snippet not in source
    assert repository_name in source


def test_platform_staff_service_uses_user_repository_for_user_persistence() -> None:
    source = (ROOT / "app/platform/services/platform_staff.py").read_text()

    assert "session.get(User" not in source
    assert "self.session.get(User" not in source
    assert "UserRepository" in source


def test_repositories_do_not_own_transactions() -> None:
    repository_files = sorted((ROOT / "app").glob("**/repositories/*.py"))
    assert repository_files

    forbidden_snippets = (
        ".commit(",
        ".rollback(",
        "await self.session.commit(",
        "await self.session.rollback(",
    )
    for repository_file in repository_files:
        source = repository_file.read_text()
        for snippet in forbidden_snippets:
            assert snippet not in source, f"{snippet} found in {repository_file}"


def test_platform_services_do_not_commit_or_rollback() -> None:
    service_files = sorted((ROOT / "app/platform/services").glob("*.py"))
    assert service_files

    for service_file in service_files:
        source = service_file.read_text()
        assert ".commit(" not in source, f"commit found in {service_file}"
        assert ".rollback(" not in source, f"rollback found in {service_file}"

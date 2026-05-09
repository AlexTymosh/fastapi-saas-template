from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from tests.helpers.asyncio_runner import run_async


def test_organisation_repository_get_by_id_respects_include_deleted(
    migrated_session_factory,
) -> None:
    async def _run() -> tuple[Organisation | None, Organisation | None]:
        async with migrated_session_factory() as session:
            async with session.begin():
                org = Organisation(
                    name="Repo Deleted",
                    slug="repo-deleted",
                    deleted_at=datetime(2026, 1, 1, tzinfo=UTC),
                )
                session.add(org)

            repo = OrganisationRepository(session)
            excluded = await repo.get_by_id(org.id)
            included = await repo.get_by_id(org.id, include_deleted=True)
            return excluded, included

    excluded, included = run_async(_run())

    assert excluded is None
    assert included is not None
    assert included.slug == "repo-deleted"


def test_organisation_repository_list_paginated_filters_deleted_and_orders_stably(
    migrated_session_factory,
) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)

    async def _run() -> tuple[list[str], int, list[str], int]:
        async with migrated_session_factory() as session:
            async with session.begin():
                orgs = [
                    Organisation(
                        id=UUID(f"00000000-0000-0000-0000-00000000000{index}"),
                        name=f"Repo Org {index}",
                        slug=f"repo-org-{index}",
                        created_at=created_at,
                    )
                    for index in range(1, 4)
                ]
                deleted = Organisation(
                    id=UUID("00000000-0000-0000-0000-000000000004"),
                    name="Repo Org Deleted",
                    slug="repo-org-deleted",
                    created_at=created_at,
                    deleted_at=datetime(2026, 1, 2, tzinfo=UTC),
                )
                session.add_all([*orgs, deleted])

        async with migrated_session_factory() as session:
            repo = OrganisationRepository(session)
            active_items, active_total = await repo.list_paginated(
                limit=10,
                offset=0,
            )
            all_items, all_total = await repo.list_paginated(
                limit=10,
                offset=0,
                include_deleted=True,
            )
            active_slugs = [
                org.slug for org in active_items if org.slug.startswith("repo-org")
            ]
            all_slugs = [
                org.slug for org in all_items if org.slug.startswith("repo-org")
            ]
            return active_slugs, active_total, all_slugs, all_total

    active_slugs, active_total, all_slugs, all_total = run_async(_run())

    assert "repo-org-deleted" not in active_slugs
    assert "repo-org-deleted" in all_slugs
    assert active_total == 3
    assert all_total == 4
    assert active_slugs == ["repo-org-3", "repo-org-2", "repo-org-1"]
    assert all_slugs == [
        "repo-org-deleted",
        "repo-org-3",
        "repo-org-2",
        "repo-org-1",
    ]


def test_organisation_repository_set_status_updates_fields_without_committing(
    migrated_session_factory, monkeypatch
) -> None:
    suspended_at = datetime(2026, 1, 2, tzinfo=UTC)

    async def _run() -> Organisation:
        async with migrated_session_factory() as session:
            async with session.begin():
                org = Organisation(name="Repo Status", slug="repo-status")
                session.add(org)

            commit = AsyncMock()
            rollback = AsyncMock()
            monkeypatch.setattr(session, "commit", commit)
            monkeypatch.setattr(session, "rollback", rollback)

            updated = await OrganisationRepository(session).set_status(
                org,
                status=OrganisationStatus.SUSPENDED,
                suspended_at=suspended_at,
                suspended_reason="policy",
            )

            commit.assert_not_awaited()
            rollback.assert_not_awaited()
            return updated

    updated = run_async(_run())

    assert updated.status == OrganisationStatus.SUSPENDED
    assert updated.suspended_at is not None
    assert updated.suspended_reason == "policy"

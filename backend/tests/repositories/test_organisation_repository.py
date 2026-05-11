from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from tests.helpers.asyncio_runner import run_async


def test_organisation_repository_soft_delete_preserves_slug_and_allows_reuse(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                repository = OrganisationRepository(session)
                deleted = await repository.create(name="Acme Old", slug="acme")
                deleted_id = deleted.id
                await repository.soft_delete(deleted)
                replacement = await repository.create(name="Acme New", slug="acme")
                replacement_id = replacement.id

        async with migrated_session_factory() as session:
            deleted = await OrganisationRepository(session).get_by_id(
                deleted_id,
                include_deleted=True,
            )
            replacement = await OrganisationRepository(session).get_by_id(
                replacement_id
            )

        assert deleted is not None
        assert deleted.deleted_at is not None
        assert deleted.slug == "acme"
        assert replacement is not None
        assert replacement.deleted_at is None
        assert replacement.slug == "acme"

    run_async(_run())


def test_organisation_repository_get_by_slug_ignores_soft_deleted_duplicate(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                deleted = Organisation(
                    name="Deleted Acme",
                    slug="acme-lookup",
                    deleted_at=datetime.now(UTC),
                )
                active = Organisation(name="Active Acme", slug="acme-lookup")
                session.add_all([deleted, active])
                await session.flush()
                active_id = active.id

        async with migrated_session_factory() as session:
            found = await OrganisationRepository(session).get_by_slug("acme-lookup")

        assert found is not None
        assert found.id == active_id
        assert found.deleted_at is None

    run_async(_run())


def test_organisation_repository_active_slug_uniqueness_is_enforced_by_database(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                await OrganisationRepository(session).create(
                    name="Acme One",
                    slug="acme-conflict",
                )

        with pytest.raises(IntegrityError):
            async with migrated_session_factory() as session:
                async with session.begin():
                    await OrganisationRepository(session).create(
                        name="Acme Two",
                        slug="acme-conflict",
                    )

    run_async(_run())


def test_organisation_repository_update_slug_to_deleted_slug_succeeds(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                deleted = Organisation(
                    name="Archived Slug",
                    slug="archived-slug",
                    deleted_at=datetime.now(UTC),
                )
                active = Organisation(name="Current Slug", slug="current-slug")
                session.add_all([deleted, active])
                await session.flush()
                active_id = active.id

        async with migrated_session_factory() as session:
            async with session.begin():
                repository = OrganisationRepository(session)
                active = await repository.get_by_id(active_id)
                assert active is not None
                updated = await repository.update_details(active, slug="archived-slug")
                assert updated.slug == "archived-slug"

        async with migrated_session_factory() as session:
            updated = await OrganisationRepository(session).get_by_id(active_id)
            assert updated is not None
            assert updated.slug == "archived-slug"

    run_async(_run())


def test_organisation_repository_update_slug_to_active_slug_fails(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                taken = Organisation(name="Taken", slug="taken-active")
                active = Organisation(name="Active", slug="free-active")
                session.add_all([taken, active])
                await session.flush()
                active_id = active.id

        with pytest.raises(IntegrityError):
            async with migrated_session_factory() as session:
                async with session.begin():
                    repository = OrganisationRepository(session)
                    active = await repository.get_by_id(active_id)
                    assert active is not None
                    await repository.update_details(active, slug="taken-active")

    run_async(_run())


def test_migrated_sqlite_database_has_active_slug_partial_unique_index(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            index_rows = (
                (await session.execute(text("PRAGMA index_list('organisations')")))
                .mappings()
                .all()
            )
            active_index = next(
                row
                for row in index_rows
                if row["name"] == "uq_organisations_slug_active"
            )
            assert active_index["unique"] == 1
            assert active_index["partial"] == 1

            sql_row = (
                (
                    await session.execute(
                        text(
                            "SELECT sql FROM sqlite_master "
                            "WHERE type = 'index' "
                            "AND name = 'uq_organisations_slug_active'"
                        )
                    )
                )
                .mappings()
                .one()
            )
            assert "deleted_at IS NULL" in sql_row["sql"]

    run_async(_run())


def test_organisation_repository_get_by_id_respects_include_deleted(
    migrated_session_factory,
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                organisation = Organisation(
                    name="Deleted Org",
                    slug="deleted-org",
                    deleted_at=datetime.now(UTC),
                )
                session.add(organisation)
            organisation_id = organisation.id

        async with migrated_session_factory() as session:
            repository = OrganisationRepository(session)
            assert await repository.get_by_id(organisation_id) is None
            assert (
                await repository.get_by_id(organisation_id, include_deleted=True)
            ) is not None

    run_async(_run())


def test_organisation_repository_list_paginated_filters_deleted_orders_and_counts(
    migrated_session_factory,
) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                organisations = [
                    Organisation(
                        id=UUID("00000000-0000-0000-0000-000000000011"),
                        name="Old Org",
                        slug="old-org",
                        created_at=base_time,
                    ),
                    Organisation(
                        id=UUID("00000000-0000-0000-0000-000000000012"),
                        name="New Low Org",
                        slug="new-low-org",
                        created_at=base_time + timedelta(minutes=1),
                    ),
                    Organisation(
                        id=UUID("00000000-0000-0000-0000-000000000013"),
                        name="New High Org",
                        slug="new-high-org",
                        created_at=base_time + timedelta(minutes=1),
                    ),
                    Organisation(
                        id=UUID("00000000-0000-0000-0000-000000000014"),
                        name="Deleted Org",
                        slug="deleted-list-org",
                        created_at=base_time + timedelta(minutes=2),
                        deleted_at=base_time + timedelta(minutes=3),
                    ),
                ]
                session.add_all(organisations)

        async with migrated_session_factory() as session:
            repository = OrganisationRepository(session)
            active_rows, active_total = await repository.list_paginated(
                limit=10,
                offset=0,
            )
            all_rows, all_total = await repository.list_paginated(
                limit=10,
                offset=0,
                include_deleted=True,
            )

        assert active_total == 3
        assert [org.slug for org in active_rows] == [
            "new-high-org",
            "new-low-org",
            "old-org",
        ]
        assert all_total == 4
        assert [org.slug for org in all_rows] == [
            "deleted-list-org",
            "new-high-org",
            "new-low-org",
            "old-org",
        ]

    run_async(_run())


def test_organisation_repository_set_status_flushes_without_committing(
    migrated_session_factory, monkeypatch
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                organisation = Organisation(name="Status Org", slug="status-org")
                session.add(organisation)
            organisation_id = organisation.id

        async with migrated_session_factory() as session:
            organisation = await OrganisationRepository(session).get_by_id(
                organisation_id
            )
            assert organisation is not None
            commit_mock = AsyncMock(side_effect=AssertionError("commit not allowed"))
            rollback_mock = AsyncMock(
                side_effect=AssertionError("rollback not allowed")
            )
            monkeypatch.setattr(session, "commit", commit_mock)
            monkeypatch.setattr(session, "rollback", rollback_mock)

            suspended_at = datetime.now(UTC)
            updated = await OrganisationRepository(session).set_status(
                organisation,
                status=OrganisationStatus.SUSPENDED,
                suspended_at=suspended_at,
                suspended_reason="policy",
            )

            assert updated.status == OrganisationStatus.SUSPENDED
            assert updated.suspended_at is not None
            assert updated.suspended_reason == "policy"
            commit_mock.assert_not_awaited()
            rollback_mock.assert_not_awaited()

    run_async(_run())

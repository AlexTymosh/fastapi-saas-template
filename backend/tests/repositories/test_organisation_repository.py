from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

from app.organisations.models.organisation import Organisation, OrganisationStatus
from app.organisations.repositories.organisations import OrganisationRepository
from tests.helpers.asyncio_runner import run_async


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

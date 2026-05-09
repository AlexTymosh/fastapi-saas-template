from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import UUID

from app.users.models.user import User, UserStatus
from app.users.repositories.users import UserRepository
from tests.helpers.asyncio_runner import run_async


def test_user_repository_list_paginated_is_deterministic_and_counts_total(
    migrated_session_factory,
) -> None:
    base_time = datetime(2026, 1, 1, tzinfo=UTC)

    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                users = [
                    User(
                        id=UUID("00000000-0000-0000-0000-000000000001"),
                        external_auth_id="repo-user-old",
                        email="repo-user-old@example.com",
                        created_at=base_time,
                    ),
                    User(
                        id=UUID("00000000-0000-0000-0000-000000000002"),
                        external_auth_id="repo-user-new-low-id",
                        email="repo-user-new-low-id@example.com",
                        created_at=base_time + timedelta(minutes=1),
                    ),
                    User(
                        id=UUID("00000000-0000-0000-0000-000000000003"),
                        external_auth_id="repo-user-new-high-id",
                        email="repo-user-new-high-id@example.com",
                        created_at=base_time + timedelta(minutes=1),
                    ),
                ]
                session.add_all(users)

        async with migrated_session_factory() as session:
            rows, total = await UserRepository(session).list_paginated(
                limit=2,
                offset=0,
            )

        assert total == 3
        assert [user.external_auth_id for user in rows] == [
            "repo-user-new-high-id",
            "repo-user-new-low-id",
        ]

    run_async(_run())


def test_user_repository_set_status_flushes_without_committing(
    migrated_session_factory, monkeypatch
) -> None:
    async def _run() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id="repo-user-status",
                    email="repo-user-status@example.com",
                )
                session.add(user)

        async with migrated_session_factory() as session:
            user = await UserRepository(session).get_by_email(
                "repo-user-status@example.com"
            )
            assert user is not None
            commit_mock = AsyncMock(side_effect=AssertionError("commit not allowed"))
            rollback_mock = AsyncMock(
                side_effect=AssertionError("rollback not allowed")
            )
            monkeypatch.setattr(session, "commit", commit_mock)
            monkeypatch.setattr(session, "rollback", rollback_mock)

            suspended_at = datetime.now(UTC)
            updated = await UserRepository(session).set_status(
                user,
                status=UserStatus.SUSPENDED,
                suspended_at=suspended_at,
                suspended_reason="policy",
            )

            assert updated.status == UserStatus.SUSPENDED
            assert updated.suspended_at is not None
            assert updated.suspended_reason == "policy"
            commit_mock.assert_not_awaited()
            rollback_mock.assert_not_awaited()

    run_async(_run())

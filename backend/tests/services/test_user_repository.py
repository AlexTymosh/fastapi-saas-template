from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID

from app.users.models.user import User, UserStatus
from app.users.repositories.users import UserRepository
from tests.helpers.asyncio_runner import run_async


def test_user_repository_list_paginated_returns_stable_order_and_total(
    migrated_session_factory,
) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)

    async def _run() -> tuple[list[str], int]:
        async with migrated_session_factory() as session:
            async with session.begin():
                users = [
                    User(
                        id=UUID(f"00000000-0000-0000-0000-00000000000{index}"),
                        external_auth_id=f"kc-repo-list-{index}",
                        email=f"repo-list-{index}@example.com",
                        email_verified=True,
                        created_at=created_at,
                    )
                    for index in range(1, 4)
                ]
                session.add_all(users)

        async with migrated_session_factory() as session:
            items, total = await UserRepository(session).list_paginated(
                limit=2,
                offset=0,
            )
            return [user.external_auth_id for user in items], total

    external_auth_ids, total = run_async(_run())

    assert total == 3
    assert external_auth_ids == ["kc-repo-list-3", "kc-repo-list-2"]


def test_user_repository_set_status_updates_fields_without_committing(
    migrated_session_factory, monkeypatch
) -> None:
    suspended_at = datetime(2026, 1, 2, tzinfo=UTC)

    async def _run() -> User:
        async with migrated_session_factory() as session:
            async with session.begin():
                user = User(
                    external_auth_id="kc-repo-status",
                    email="repo-status@example.com",
                    email_verified=True,
                )
                session.add(user)

            commit = AsyncMock()
            rollback = AsyncMock()
            monkeypatch.setattr(session, "commit", commit)
            monkeypatch.setattr(session, "rollback", rollback)

            updated = await UserRepository(session).set_status(
                user,
                status=UserStatus.SUSPENDED,
                suspended_at=suspended_at,
                suspended_reason="policy",
            )

            commit.assert_not_awaited()
            rollback.assert_not_awaited()
            return updated

    updated = run_async(_run())

    assert updated.status == UserStatus.SUSPENDED
    assert updated.suspended_at is not None
    assert updated.suspended_reason == "policy"

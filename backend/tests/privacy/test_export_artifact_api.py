from __future__ import annotations

import pytest

from app.users.services.users import UserService
from tests.helpers.asyncio_runner import run_async
from tests.helpers.auth import identity_for

pytestmark = [pytest.mark.privacy, pytest.mark.authz]


def test_unauthenticated_user_cannot_list_export_artifacts(
    client_factory, migrated_database_url
) -> None:
    client = client_factory(database_url=migrated_database_url)
    response = client.get("/api/v1/privacy/export-artifacts")
    assert response.status_code == 401


def test_authenticated_user_can_call_export_artifact_list(
    authenticated_client_factory, migrated_database_url, migrated_session_factory
) -> None:
    async def _provision() -> None:
        async with migrated_session_factory() as session:
            async with session.begin():
                await UserService(session).provision_current_user(
                    identity_for("kc-user-export", "export-user@example.com")
                )

    run_async(_provision())

    bundle = authenticated_client_factory(
        identity=identity_for("kc-user-export", "export-user@example.com"),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/privacy/export-artifacts")
    assert response.status_code == 200
    assert set(response.json().keys()) == {"data", "meta", "links"}

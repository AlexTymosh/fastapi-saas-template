from tests.helpers.auth import identity_for


def test_platform_user_suspend_requires_reason(
    authenticated_client_factory, migrated_database_url
) -> None:
    bundle = authenticated_client_factory(
        identity=identity_for("kc-platform-admin-1", "platform-admin-1@example.com"),
        database_url=migrated_database_url,
    )
    response = bundle.client.post(
        "/api/v1/platform/users/00000000-0000-0000-0000-000000000001/suspend", json={}
    )
    assert response.status_code == 422

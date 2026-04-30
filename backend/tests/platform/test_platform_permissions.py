from tests.helpers.auth import identity_for


def test_jwt_platform_admin_without_platform_staff_gets_403(
    authenticated_client_factory, migrated_database_url
) -> None:
    bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-platform-no-staff",
            "platform-no-staff@example.com",
            roles=["platform_admin"],
        ),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/platform/users")
    assert response.status_code == 403


def test_jwt_superadmin_without_platform_staff_gets_403(
    authenticated_client_factory, migrated_database_url
) -> None:
    bundle = authenticated_client_factory(
        identity=identity_for(
            "kc-superadmin-no-staff",
            "superadmin-no-staff@example.com",
            roles=["superadmin"],
        ),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/platform/users")
    assert response.status_code == 403

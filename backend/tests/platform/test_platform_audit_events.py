from tests.helpers.auth import identity_for


def test_platform_audit_events_limit_validation(
    authenticated_client_factory, migrated_database_url
) -> None:
    bundle = authenticated_client_factory(
        identity=identity_for("kc-platform-audit-1", "platform-audit-1@example.com"),
        database_url=migrated_database_url,
    )
    response = bundle.client.get("/api/v1/platform/audit-events?limit=101")
    assert response.status_code == 422

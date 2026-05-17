from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.security, pytest.mark.authz]
_REALM_EXPORT = (
    Path(__file__).resolve().parents[3] / "docker/keycloak/realm-export.json"
)
_BACKEND_ROLE_NAMES = {
    "superadmin",
    "platform_admin",
    "support_agent",
    "compliance_officer",
    "owner",
    "admin",
    "member",
}


def _realm_export() -> dict[str, object]:
    return json.loads(_REALM_EXPORT.read_text())


def _client(realm: dict[str, object], client_id: str) -> dict[str, object]:
    clients = realm.get("clients", [])
    assert isinstance(clients, list)
    matches = [client for client in clients if client.get("clientId") == client_id]
    assert len(matches) == 1
    return matches[0]


def test_realm_export_does_not_define_backend_authorization_roles() -> None:
    realm = _realm_export()
    roles = realm.get("roles", {})
    assert isinstance(roles, dict)
    realm_roles = roles.get("realm", [])
    assert isinstance(realm_roles, list)

    role_names = {role.get("name") for role in realm_roles}

    assert role_names.isdisjoint(_BACKEND_ROLE_NAMES)


def test_seed_users_do_not_receive_backend_authorization_realm_roles() -> None:
    realm = _realm_export()
    users = realm.get("users", [])
    assert isinstance(users, list)

    for user in users:
        realm_roles = set(user.get("realmRoles", []))
        assert realm_roles.isdisjoint(_BACKEND_ROLE_NAMES)


def test_default_client_scopes_do_not_include_roles_scope() -> None:
    realm = _realm_export()
    web_client = _client(realm, "fastapi-web")
    api_client = _client(realm, "fastapi-api")

    web_default_scopes = web_client.get("defaultClientScopes", [])
    api_default_scopes = api_client.get("defaultClientScopes", [])

    assert "roles" not in web_default_scopes
    assert "roles" not in api_default_scopes
    assert set(web_default_scopes) >= {"profile", "email"}
    assert api_default_scopes == []


def test_fastapi_web_keeps_fastapi_api_audience_mapper() -> None:
    realm = _realm_export()
    web_client = _client(realm, "fastapi-web")
    mappers = web_client.get("protocolMappers", [])
    assert isinstance(mappers, list)

    audience_mapper = next(
        (mapper for mapper in mappers if mapper.get("name") == "aud-fastapi-api"),
        None,
    )

    assert audience_mapper is not None
    assert audience_mapper["protocolMapper"] == "oidc-audience-mapper"
    assert audience_mapper["config"]["included.client.audience"] == "fastapi-api"
    assert audience_mapper["config"]["access.token.claim"] == "true"


def test_fastapi_api_remains_non_interactive_audience_client() -> None:
    realm = _realm_export()
    api_client = _client(realm, "fastapi-api")

    assert api_client["standardFlowEnabled"] is False
    assert api_client["directAccessGrantsEnabled"] is False
    assert api_client["serviceAccountsEnabled"] is False
    assert api_client["implicitFlowEnabled"] is False

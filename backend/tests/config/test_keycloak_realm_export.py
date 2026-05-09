from __future__ import annotations

import json
from pathlib import Path

import pytest

pytestmark = [pytest.mark.security, pytest.mark.authz]

REPO_ROOT = Path(__file__).resolve().parents[3]
REALM_EXPORT_PATH = REPO_ROOT / "docker" / "keycloak" / "realm-export.json"
FORBIDDEN_BACKEND_ROLES = {
    "superadmin",
    "platform_admin",
    "support_agent",
    "compliance_officer",
    "owner",
    "admin",
    "member",
}


def _load_realm_export() -> dict[str, object]:
    return json.loads(REALM_EXPORT_PATH.read_text())


def _clients_by_id(realm: dict[str, object]) -> dict[str, dict[str, object]]:
    clients = realm.get("clients", [])
    assert isinstance(clients, list)
    return {client["clientId"]: client for client in clients}


def test_realm_export_does_not_define_backend_authorization_roles():
    realm = _load_realm_export()
    roles = realm.get("roles", {})
    assert isinstance(roles, dict)
    realm_roles = roles.get("realm", [])
    assert isinstance(realm_roles, list)

    role_names = {role.get("name") for role in realm_roles if isinstance(role, dict)}

    assert role_names.isdisjoint(FORBIDDEN_BACKEND_ROLES)


def test_seed_users_do_not_receive_backend_authorization_realm_roles():
    realm = _load_realm_export()
    users = realm.get("users", [])
    assert isinstance(users, list)

    for user in users:
        assert isinstance(user, dict)
        assigned_roles = set(user.get("realmRoles", []))
        assert assigned_roles.isdisjoint(FORBIDDEN_BACKEND_ROLES)


def test_clients_do_not_attach_roles_default_scope_and_keep_identity_scopes():
    realm = _load_realm_export()
    clients = _clients_by_id(realm)

    web_client = clients["fastapi-web"]
    api_client = clients["fastapi-api"]

    assert "roles" not in web_client.get("defaultClientScopes", [])
    assert "roles" not in api_client.get("defaultClientScopes", [])
    assert web_client.get("defaultClientScopes") == ["profile", "email"]
    assert api_client.get("defaultClientScopes") == []


def test_fastapi_web_keeps_fastapi_api_audience_mapper():
    realm = _load_realm_export()
    web_client = _clients_by_id(realm)["fastapi-web"]
    mappers = web_client.get("protocolMappers", [])
    assert isinstance(mappers, list)

    audience_mapper = next(
        mapper
        for mapper in mappers
        if isinstance(mapper, dict) and mapper.get("name") == "aud-fastapi-api"
    )

    assert audience_mapper.get("protocol") == "openid-connect"
    assert audience_mapper.get("protocolMapper") == "oidc-audience-mapper"
    assert audience_mapper.get("config") == {
        "included.client.audience": "fastapi-api",
        "id.token.claim": "false",
        "access.token.claim": "true",
    }


def test_fastapi_api_client_remains_non_interactive_audience_client():
    realm = _load_realm_export()
    api_client = _clients_by_id(realm)["fastapi-api"]

    assert api_client["standardFlowEnabled"] is False
    assert api_client["directAccessGrantsEnabled"] is False
    assert api_client["serviceAccountsEnabled"] is False
    assert api_client["implicitFlowEnabled"] is False

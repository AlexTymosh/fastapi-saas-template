from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from tests.helpers.jwt import generate_rsa_jwk, issue_access_token


def test_users_me_accepts_validated_jwt_with_api_audience_and_web_resource_roles(
    monkeypatch,
    migrated_database_url: str,
) -> None:
    issuer = "http://localhost:8080/realms/fastapi-saas"
    jwks_url = "http://mock-idp/jwks"
    discovery_url = f"{issuer}/.well-known/openid-configuration"

    jwk, private_key = generate_rsa_jwk()

    def _fetch(url: str) -> dict[str, object]:
        if url == discovery_url:
            return {"jwks_uri": jwks_url}
        if url == jwks_url:
            return {"keys": [jwk]}
        raise AssertionError(f"Unexpected URL requested: {url}")

    monkeypatch.setenv("DATABASE__URL", migrated_database_url)
    monkeypatch.setenv("AUTH__ENABLED", "true")
    monkeypatch.setenv("AUTH__ISSUER_URL", issuer)
    monkeypatch.setenv("AUTH__AUDIENCE", "fastapi-api")
    monkeypatch.setenv("AUTH__CLIENT_ID", "fastapi-web")

    import app.core.auth_jwt as auth_jwt_module

    monkeypatch.setattr(auth_jwt_module, "_fetch_json_url", _fetch)
    monkeypatch.setattr(auth_jwt_module, "_jwt_validator", None)
    monkeypatch.setattr(auth_jwt_module, "_jwt_validator_signature", None)

    token = issue_access_token(
        private_key=private_key,
        kid=jwk["kid"],
        issuer=issuer,
        audience="fastapi-api",
        subject="kc-e2e-user-1",
        claims={
            "email": "jwt-path@example.com",
            "email_verified": True,
            "given_name": "JWT",
            "family_name": "Path",
            "realm_access": {"roles": ["member"]},
            "resource_access": {"fastapi-web": {"roles": ["org-admin"]}},
        },
    )

    app = create_app()
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/users/me",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["external_auth_id"] == "kc-e2e-user-1"
    assert payload["email"] == "jwt-path@example.com"

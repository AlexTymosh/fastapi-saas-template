from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.auth import AuthenticatedPrincipal, JwtClaimsPayload


def test_jwt_claim_mapping_supports_standard_name_claims() -> None:
    claims = JwtClaimsPayload.model_validate(
        {
            "sub": "kc-user-claims-1",
            "email": "claims@example.com",
            "email_verified": True,
            "given_name": "Given",
            "family_name": "Family",
        }
    )

    principal = claims.to_authenticated_principal()

    assert principal == AuthenticatedPrincipal(
        external_auth_id="kc-user-claims-1",
        email="claims@example.com",
        email_verified=True,
        first_name="Given",
        last_name="Family",
    )


def test_jwt_claim_mapping_supports_first_and_last_name_fallback_keys() -> None:
    principal = AuthenticatedPrincipal.from_unverified_jwt_claims(
        {
            "sub": "kc-user-claims-2",
            "email": "claims2@example.com",
            "first_name": "First",
            "last_name": "Last",
        }
    )

    assert principal.external_auth_id == "kc-user-claims-2"
    assert principal.first_name == "First"
    assert principal.last_name == "Last"


def test_jwt_claim_mapping_rejects_invalid_email_claim() -> None:
    with pytest.raises(ValidationError):
        AuthenticatedPrincipal.from_unverified_jwt_claims(
            {
                "sub": "kc-user-claims-invalid-email",
                "email": "not-an-email",
            }
        )


def test_principal_superadmin_flag_comes_from_roles_claim() -> None:
    principal = AuthenticatedPrincipal.from_unverified_jwt_claims(
        {
            "sub": "kc-super-1",
            "email": "super@example.com",
            "roles": ["superadmin"],
        }
    )

    assert principal.is_superadmin() is True


def test_verified_claim_mapping_merges_keycloak_realm_and_client_roles() -> None:
    principal = AuthenticatedPrincipal.from_verified_jwt_claims(
        {
            "sub": "kc-user-claims-roles",
            "realm_access": {"roles": ["member", "admin"]},
            "resource_access": {
                "fastapi-backend": {"roles": ["admin", "editor"]},
            },
        },
        resource_client_id="fastapi-backend",
    )

    assert principal.platform_roles == ["member", "admin", "editor"]

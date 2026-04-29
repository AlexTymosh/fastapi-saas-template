from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field


class JwtClaimsPayload(BaseModel):
    """Canonical JWT claims payload expected from upstream identity provider."""

    model_config = ConfigDict(extra="ignore")

    external_auth_id: str = Field(
        min_length=1,
        validation_alias="sub",
    )
    email: EmailStr | None = None
    email_verified: bool = False
    first_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("given_name", "first_name"),
    )
    last_name: str | None = Field(
        default=None,
        validation_alias=AliasChoices("family_name", "last_name"),
    )
    platform_roles: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("platform_roles", "roles"),
    )

    def to_authenticated_principal(self) -> AuthenticatedPrincipal:
        return AuthenticatedPrincipal.model_validate(self.model_dump())


class AuthenticatedPrincipal(BaseModel):
    """
    Auth boundary contract passed to application services.

    JWT claims mapping contract (future verified token -> local principal):
    - sub -> external_auth_id
    - email -> email
    - email_verified -> email_verified
    - given_name / first_name -> first_name
    - family_name / last_name -> last_name
    - roles/platform_roles -> platform_roles
    """

    model_config = ConfigDict(extra="ignore")

    external_auth_id: str = Field(min_length=1)
    email: EmailStr | None = None
    email_verified: bool = False
    first_name: str | None = None
    last_name: str | None = None
    platform_roles: list[str] = Field(default_factory=list)

    @classmethod
    def from_unverified_jwt_claims(
        cls, claims: dict[str, object]
    ) -> AuthenticatedPrincipal:
        payload = JwtClaimsPayload.model_validate(claims)
        return payload.to_authenticated_principal()

    @classmethod
    def from_verified_jwt_claims(
        cls,
        claims: dict[str, object],
        *,
        resource_client_id: str | None,
    ) -> AuthenticatedPrincipal:
        payload = JwtClaimsPayload.model_validate(
            {
                **claims,
                "platform_roles": extract_platform_roles(
                    claims,
                    resource_client_id=resource_client_id,
                ),
            }
        )
        return payload.to_authenticated_principal()


def extract_platform_roles(
    claims: dict[str, object],
    *,
    resource_client_id: str | None,
) -> list[str]:
    merged_roles: list[str] = []

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        realm_roles = realm_access.get("roles")
        if isinstance(realm_roles, list):
            merged_roles.extend(_coerce_roles(realm_roles))

    if resource_client_id:
        resource_access = claims.get("resource_access")
        if isinstance(resource_access, dict):
            client_access = resource_access.get(resource_client_id)
            if isinstance(client_access, dict):
                client_roles = client_access.get("roles")
                if isinstance(client_roles, list):
                    merged_roles.extend(_coerce_roles(client_roles))

    direct_roles = claims.get("platform_roles") or claims.get("roles")
    if isinstance(direct_roles, list):
        merged_roles.extend(_coerce_roles(direct_roles))

    unique_roles: list[str] = []
    seen: set[str] = set()
    for role in merged_roles:
        if role not in seen:
            seen.add(role)
            unique_roles.append(role)

    return unique_roles


def _coerce_roles(values: list[Any]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]

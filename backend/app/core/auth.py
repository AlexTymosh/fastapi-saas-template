from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any
from urllib.error import URLError
from urllib.request import urlopen

import jwt
from fastapi import Depends, Request
from jwt import InvalidAudienceError, InvalidIssuerError, InvalidTokenError
from jwt.algorithms import RSAAlgorithm
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field

from app.core.config.settings import AuthSettings, Settings, get_settings
from app.core.errors.exceptions import UnauthorizedError


@dataclass
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


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

    def is_superadmin(self) -> bool:
        return any(role.lower() == "superadmin" for role in self.platform_roles)

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
                "platform_roles": _extract_platform_roles(
                    claims,
                    resource_client_id=resource_client_id,
                ),
            }
        )
        return payload.to_authenticated_principal()


class JwtValidator:
    def __init__(
        self,
        *,
        auth_settings: AuthSettings,
        fetch_json: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self.auth_settings = auth_settings
        self._fetch_json = fetch_json or _fetch_json_url
        self._discovery_cache: _CacheEntry | None = None
        self._jwks_cache: _CacheEntry | None = None

    async def validate_token(self, token: str) -> dict[str, object]:
        if not self.auth_settings.enabled:
            raise UnauthorizedError(detail="Authentication is disabled")

        issuer = self.auth_settings.issuer_url
        if not issuer:
            raise UnauthorizedError(detail="Token issuer is not configured")

        allowed_algorithms = set(self.auth_settings.algorithms)
        if allowed_algorithms != {"RS256"}:
            raise UnauthorizedError(
                detail="Unsupported token signing algorithm configuration"
            )

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise UnauthorizedError(detail="Invalid bearer token") from exc

        token_alg = str(header.get("alg") or "")
        if token_alg not in allowed_algorithms:
            raise UnauthorizedError(detail="Token signing algorithm is not allowed")

        jwks = await self._get_jwks()
        key = self._resolve_signing_key(jwks, header)

        decode_kwargs: dict[str, object] = {
            "key": key,
            "algorithms": list(allowed_algorithms),
            "issuer": issuer,
            "leeway": self.auth_settings.leeway_seconds,
            "options": {"require": ["exp", "iss", "sub"]},
        }

        if self.auth_settings.audience:
            decode_kwargs["audience"] = self.auth_settings.audience

        try:
            decoded = jwt.decode(token, **decode_kwargs)
        except InvalidIssuerError as exc:
            raise UnauthorizedError(detail="Invalid token issuer") from exc
        except InvalidAudienceError as exc:
            raise UnauthorizedError(detail="Invalid token audience") from exc
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError(detail="Token has expired") from exc
        except InvalidTokenError as exc:
            raise UnauthorizedError(detail="Invalid bearer token") from exc

        if not isinstance(decoded, dict):
            raise UnauthorizedError(detail="Invalid bearer token")

        return decoded

    async def _get_jwks(self) -> dict[str, Any]:
        if self._jwks_cache and self._jwks_cache.expires_at > time.time():
            return self._jwks_cache.value

        jwks_url = self.auth_settings.jwks_url
        if jwks_url is None:
            discovery = await self._get_discovery_document()
            jwks_uri = discovery.get("jwks_uri")
            if not isinstance(jwks_uri, str) or not jwks_uri:
                raise UnauthorizedError(detail="OIDC discovery is missing jwks_uri")
            jwks_url = jwks_uri

        jwks = await self._fetch_json_async(jwks_url)
        self._jwks_cache = _CacheEntry(
            value=jwks,
            expires_at=time.time() + self.auth_settings.jwks_cache_ttl_seconds,
        )
        return jwks

    async def _get_discovery_document(self) -> dict[str, Any]:
        if self._discovery_cache and self._discovery_cache.expires_at > time.time():
            return self._discovery_cache.value

        if not self.auth_settings.issuer_url:
            raise UnauthorizedError(detail="Token issuer is not configured")

        issuer = self.auth_settings.issuer_url.rstrip("/")
        discovery_url = f"{issuer}/.well-known/openid-configuration"
        document = await self._fetch_json_async(discovery_url)
        self._discovery_cache = _CacheEntry(
            value=document,
            expires_at=time.time()
            + self.auth_settings.discovery_cache_ttl_seconds,
        )
        return document

    def _resolve_signing_key(
        self,
        jwks: dict[str, Any],
        header: dict[str, Any],
    ) -> Any:
        kid = header.get("kid")
        keys = jwks.get("keys")

        if not isinstance(keys, list) or not keys:
            raise UnauthorizedError(detail="JWKS does not contain signing keys")

        for jwk in keys:
            if isinstance(jwk, dict) and jwk.get("kid") == kid:
                return self._public_key_from_jwk(jwk)

        raise UnauthorizedError(detail="Unable to match token signing key")

    def _public_key_from_jwk(self, jwk: dict[str, Any]) -> Any:
        kty = jwk.get("kty")
        if kty != "RSA":
            raise UnauthorizedError(detail="Unsupported signing key type")

        try:
            return RSAAlgorithm.from_jwk(json.dumps(jwk))
        except Exception as exc:
            raise UnauthorizedError(detail="Invalid JWKS signing key") from exc

    async def _fetch_json_async(self, url: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._fetch_json, url)
        except UnauthorizedError:
            raise
        except Exception as exc:
            raise UnauthorizedError(detail="Unable to fetch identity metadata") from exc

        if not isinstance(result, dict):
            raise UnauthorizedError(detail="Identity metadata payload is invalid")

        return result


def _extract_platform_roles(
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


def _coerce_roles(values: list[object]) -> list[str]:
    return [str(value).strip() for value in values if str(value).strip()]


def _extract_bearer_token(request: Request) -> str | None:
    auth_header = request.headers.get("Authorization")
    if auth_header is None:
        return None

    parts = auth_header.strip().split()
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise UnauthorizedError(detail="Malformed Authorization header")

    return parts[1].strip()


def _fetch_json_url(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
            return json.loads(payload)
    except (URLError, json.JSONDecodeError) as exc:
        raise UnauthorizedError(detail="Unable to fetch identity metadata") from exc


_jwt_validator: JwtValidator | None = None
_jwt_validator_signature: tuple[object, ...] | None = None


def _validator_signature(settings: Settings) -> tuple[object, ...]:
    return (
        settings.auth.enabled,
        settings.auth.issuer_url,
        settings.auth.audience,
        settings.auth.jwks_url,
        tuple(settings.auth.algorithms),
        settings.auth.leeway_seconds,
        settings.auth.discovery_cache_ttl_seconds,
        settings.auth.jwks_cache_ttl_seconds,
    )


def _get_jwt_validator(settings: Settings) -> JwtValidator:
    global _jwt_validator, _jwt_validator_signature

    signature = _validator_signature(settings)
    if _jwt_validator is None or signature != _jwt_validator_signature:
        _jwt_validator = JwtValidator(auth_settings=settings.auth)
        _jwt_validator_signature = signature

    return _jwt_validator


async def get_authenticated_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    token = _extract_bearer_token(request)
    if token is None:
        return None

    settings = get_settings()
    claims = await _get_jwt_validator(settings).validate_token(token)

    return AuthenticatedPrincipal.from_verified_jwt_claims(
        claims,
        resource_client_id=settings.auth.client_id,
    )


async def require_authenticated_principal(
    principal: Annotated[
        AuthenticatedPrincipal | None,
        Depends(get_authenticated_principal),
    ],
) -> AuthenticatedPrincipal:
    if principal is None:
        raise UnauthorizedError(detail="Authentication required")
    return principal

from __future__ import annotations

import base64
import hashlib
import json
from functools import lru_cache
from time import monotonic, time
from typing import Annotated, Any
from urllib.parse import urljoin
from urllib.request import urlopen

from fastapi import Depends, Request
from pydantic import AliasChoices, BaseModel, ConfigDict, EmailStr, Field

from app.core.config.settings import get_settings
from app.core.errors.exceptions import UnauthorizedError

_SHA256_DER_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


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


class KeycloakJwtAuthenticator:
    def __init__(self) -> None:
        self._discovery_cache: tuple[float, dict[str, Any]] | None = None
        self._jwks_cache: tuple[float, dict[str, Any]] | None = None

    def authenticate(
        self,
        authorization_header: str | None,
    ) -> AuthenticatedPrincipal | None:
        settings = get_settings().auth

        if authorization_header is None:
            return None
        if not settings.enabled:
            raise UnauthorizedError(detail="Bearer authentication is disabled")

        token = self._extract_bearer_token(authorization_header)
        claims = self._decode_and_verify(token)
        return self._map_claims_to_principal(claims, client_id=settings.client_id)

    def _extract_bearer_token(self, header: str) -> str:
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or not token.strip() or " " in token.strip():
            raise UnauthorizedError(detail="Malformed Authorization header")
        return token.strip()

    def _decode_and_verify(self, token: str) -> dict[str, Any]:
        header, claims, signing_input, signature = _decode_jwt(token)
        settings = get_settings().auth

        algorithm = header.get("alg")
        key_id = header.get("kid")
        if algorithm not in settings.algorithms:
            raise UnauthorizedError(detail="Token uses a disallowed algorithm")
        if algorithm != "RS256":
            raise UnauthorizedError(detail="Unsupported token algorithm")
        if not isinstance(key_id, str) or not key_id:
            raise UnauthorizedError(detail="Token header is missing key identifier")

        signing_key = self._resolve_signing_key(key_id=key_id)
        _verify_rs256_signature(signing_input, signature, signing_key)

        _validate_registered_claims(claims)
        _validate_issuer(claims)
        _validate_audience(claims)
        return claims

    def _resolve_signing_key(self, *, key_id: str) -> dict[str, Any]:
        jwks = self._get_jwks_document()
        keys = jwks.get("keys")
        if not isinstance(keys, list):
            raise UnauthorizedError(detail="JWKS payload is invalid")

        for key in keys:
            if isinstance(key, dict) and key.get("kid") == key_id:
                return key

        raise UnauthorizedError(detail="Unable to find matching JWKS key")

    def _get_jwks_document(self) -> dict[str, Any]:
        settings = get_settings().auth
        now = monotonic()

        if self._jwks_cache is not None and self._jwks_cache[0] > now:
            return self._jwks_cache[1]

        jwks_url = settings.jwks_url or self._discover_jwks_url()
        payload = _fetch_json_document(jwks_url)
        self._jwks_cache = (now + settings.jwks_cache_ttl_seconds, payload)
        return payload

    def _discover_jwks_url(self) -> str:
        settings = get_settings().auth
        now = monotonic()

        if self._discovery_cache is not None and self._discovery_cache[0] > now:
            cached_jwks_uri = self._discovery_cache[1].get("jwks_uri")
            if isinstance(cached_jwks_uri, str) and cached_jwks_uri:
                return cached_jwks_uri

        issuer = settings.issuer_url
        if not issuer:
            raise UnauthorizedError(detail="Auth issuer is not configured")

        discovery_url = urljoin(
            issuer.rstrip("/") + "/",
            ".well-known/openid-configuration",
        )
        payload = _fetch_json_document(discovery_url)
        jwks_uri = payload.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise UnauthorizedError(detail="OIDC discovery response is invalid")

        self._discovery_cache = (now + settings.discovery_cache_ttl_seconds, payload)
        return jwks_uri

    def _map_claims_to_principal(
        self,
        claims: dict[str, Any],
        *,
        client_id: str | None,
    ) -> AuthenticatedPrincipal:
        platform_roles = _extract_platform_roles(claims, client_id=client_id)
        mapped_claims = dict(claims)
        mapped_claims["platform_roles"] = platform_roles
        return AuthenticatedPrincipal.from_unverified_jwt_claims(mapped_claims)


@lru_cache(maxsize=1)
def get_keycloak_authenticator() -> KeycloakJwtAuthenticator:
    return KeycloakJwtAuthenticator()


def _decode_jwt(token: str) -> tuple[dict[str, Any], dict[str, Any], bytes, bytes]:
    parts = token.split(".")
    if len(parts) != 3:
        raise UnauthorizedError(detail="Invalid bearer token")

    header_segment, payload_segment, signature_segment = parts

    try:
        header = json.loads(_base64url_decode(header_segment))
        payload = json.loads(_base64url_decode(payload_segment))
        signature = _base64url_decode(signature_segment)
    except Exception as exc:
        raise UnauthorizedError(detail="Invalid bearer token") from exc

    if not isinstance(header, dict) or not isinstance(payload, dict):
        raise UnauthorizedError(detail="Invalid bearer token")

    signing_input = f"{header_segment}.{payload_segment}".encode()
    return header, payload, signing_input, signature


def _fetch_json_document(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:  # pragma: no cover
        raise UnauthorizedError(detail="Unable to fetch identity metadata") from exc

    if not isinstance(payload, dict):
        raise UnauthorizedError(detail="Identity metadata response is invalid")
    return payload


def _base64url_decode(segment: str) -> bytes:
    padded = segment + ("=" * ((4 - len(segment) % 4) % 4))
    return base64.urlsafe_b64decode(padded)


def _verify_rs256_signature(
    signing_input: bytes,
    signature: bytes,
    jwk: dict[str, Any],
) -> None:
    if jwk.get("kty") != "RSA":
        raise UnauthorizedError(detail="Unsupported JWKS key type")

    try:
        modulus = int.from_bytes(_base64url_decode(str(jwk["n"])), byteorder="big")
        exponent = int.from_bytes(_base64url_decode(str(jwk["e"])), byteorder="big")
    except Exception as exc:
        raise UnauthorizedError(detail="Invalid JWKS key material") from exc

    key_size_bytes = (modulus.bit_length() + 7) // 8
    if len(signature) != key_size_bytes:
        raise UnauthorizedError(detail="Invalid bearer token signature")

    signature_int = int.from_bytes(signature, byteorder="big")
    decoded_block = pow(signature_int, exponent, modulus).to_bytes(
        key_size_bytes,
        byteorder="big",
    )

    digest = hashlib.sha256(signing_input).digest()
    digest_info = _SHA256_DER_PREFIX + digest
    padding_length = key_size_bytes - len(digest_info) - 3
    if padding_length < 8:
        raise UnauthorizedError(detail="Invalid bearer token signature")

    expected = b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    if decoded_block != expected:
        raise UnauthorizedError(detail="Invalid bearer token signature")


def _validate_registered_claims(claims: dict[str, Any]) -> None:
    if "sub" not in claims or not isinstance(claims["sub"], str) or not claims["sub"]:
        raise UnauthorizedError(detail="Invalid bearer token")

    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        raise UnauthorizedError(detail="Invalid bearer token")

    leeway = get_settings().auth.leeway_seconds
    if time() > (float(exp) + leeway):
        raise UnauthorizedError(detail="Invalid bearer token")


def _validate_issuer(claims: dict[str, Any]) -> None:
    issuer = get_settings().auth.issuer_url
    if not issuer:
        raise UnauthorizedError(detail="Auth issuer is not configured")

    if claims.get("iss") != issuer:
        raise UnauthorizedError(detail="Invalid bearer token")


def _validate_audience(claims: dict[str, Any]) -> None:
    audience = get_settings().auth.audience
    if not audience:
        return

    claim_aud = claims.get("aud")
    if isinstance(claim_aud, str):
        is_valid = claim_aud == audience
    elif isinstance(claim_aud, list):
        is_valid = audience in claim_aud
    else:
        is_valid = False

    if not is_valid:
        raise UnauthorizedError(detail="Invalid bearer token")


def _extract_platform_roles(
    claims: dict[str, Any],
    *,
    client_id: str | None,
) -> list[str]:
    roles: list[str] = []

    def _append_role_candidates(candidates: Any) -> None:
        if not isinstance(candidates, list):
            return
        for candidate in candidates:
            if isinstance(candidate, str) and candidate and candidate not in roles:
                roles.append(candidate)

    _append_role_candidates(claims.get("platform_roles"))
    _append_role_candidates(claims.get("roles"))

    realm_access = claims.get("realm_access")
    if isinstance(realm_access, dict):
        _append_role_candidates(realm_access.get("roles"))

    if client_id:
        resource_access = claims.get("resource_access")
        if isinstance(resource_access, dict):
            client_resource = resource_access.get(client_id)
            if isinstance(client_resource, dict):
                _append_role_candidates(client_resource.get("roles"))

    return roles


async def get_authenticated_principal(
    request: Request,
) -> AuthenticatedPrincipal | None:
    authorization_header = request.headers.get("Authorization")
    return get_keycloak_authenticator().authenticate(authorization_header)


async def require_authenticated_principal(
    principal: Annotated[
        AuthenticatedPrincipal | None,
        Depends(get_authenticated_principal),
    ],
) -> AuthenticatedPrincipal:
    if principal is None:
        raise UnauthorizedError(detail="Authentication required")
    return principal

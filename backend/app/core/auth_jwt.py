from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

import jwt
from jwt import InvalidAudienceError, InvalidIssuerError, InvalidTokenError
from jwt.algorithms import get_default_algorithms

from app.core.config.settings import AuthSettings, Settings
from app.core.errors.exceptions import UnauthorizedError


@dataclass
class _CacheEntry:
    value: dict[str, Any]
    expires_at: float


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

        allowed_algorithms = {self.auth_settings.algorithm}

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise UnauthorizedError(detail="Invalid bearer token") from exc

        token_alg = str(header.get("alg") or "")
        if token_alg not in allowed_algorithms:
            raise UnauthorizedError(detail="Token signing algorithm is not allowed")

        key = await self._resolve_signing_key(header)

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

    async def _resolve_signing_key(self, header: dict[str, Any]) -> Any:
        jwks = await self._get_jwks()
        key = self._resolve_signing_key_from_jwks(jwks, header)
        if key is not None:
            return key

        # Key rotation safe retry: refresh JWKS once, then retry the same lookup.
        self._jwks_cache = None
        refreshed_jwks = await self._get_jwks()
        refreshed_key = self._resolve_signing_key_from_jwks(refreshed_jwks, header)
        if refreshed_key is not None:
            return refreshed_key

        raise UnauthorizedError(detail="Unable to match token signing key")

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
            expires_at=time.time() + self.auth_settings.discovery_cache_ttl_seconds,
        )
        return document

    def _resolve_signing_key_from_jwks(
        self,
        jwks: dict[str, Any],
        header: dict[str, Any],
    ) -> Any | None:
        kid = header.get("kid")
        keys = jwks.get("keys")

        if not isinstance(keys, list) or not keys:
            raise UnauthorizedError(detail="JWKS does not contain signing keys")

        for jwk in keys:
            if isinstance(jwk, dict) and jwk.get("kid") == kid:
                return self._public_key_from_jwk(jwk)

        return None

    def _public_key_from_jwk(self, jwk: dict[str, Any]) -> Any:
        kty = jwk.get("kty")
        algorithm_loader = get_default_algorithms().get("RS256")

        if kty != "RSA" or algorithm_loader is None:
            raise UnauthorizedError(detail="Unsupported signing key type")

        try:
            return algorithm_loader.from_jwk(json.dumps(jwk))
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
        settings.auth.algorithm,
        settings.auth.leeway_seconds,
        settings.auth.discovery_cache_ttl_seconds,
        settings.auth.jwks_cache_ttl_seconds,
    )


def get_jwt_validator(settings: Settings) -> JwtValidator:
    global _jwt_validator, _jwt_validator_signature

    signature = _validator_signature(settings)
    if _jwt_validator is None or signature != _jwt_validator_signature:
        _jwt_validator = JwtValidator(auth_settings=settings.auth)
        _jwt_validator_signature = signature

    return _jwt_validator

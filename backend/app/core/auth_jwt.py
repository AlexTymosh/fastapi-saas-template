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
from jwt import (
    ExpiredSignatureError,
    InvalidAudienceError,
    InvalidIssuerError,
    InvalidTokenError,
)
from jwt.algorithms import get_default_algorithms

from app.core.config.settings import AuthSettings, Settings
from app.core.errors.exceptions import UnauthorizedError


@dataclass(slots=True)
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
        self._jwks_refresh_lock = asyncio.Lock()
        self._last_forced_jwks_refresh_at = 0.0

    async def validate_token(self, token: str) -> dict[str, Any]:
        if not self.auth_settings.enabled:
            raise UnauthorizedError(detail="Invalid bearer token")

        try:
            header = jwt.get_unverified_header(token)
        except InvalidTokenError as exc:
            raise UnauthorizedError(detail="Invalid bearer token") from exc

        if not isinstance(header, dict):
            raise UnauthorizedError(detail="Invalid bearer token")

        if header.get("alg") != self.auth_settings.algorithms:
            raise UnauthorizedError(detail="Invalid bearer token")

        kid = header.get("kid")
        if self.auth_settings.require_kid and not isinstance(kid, str):
            raise UnauthorizedError(detail="Invalid bearer token")

        signing_key = await self._resolve_signing_key(header)
        required_claims = ["exp", "iss", "sub"]
        if self.auth_settings.audience:
            required_claims.append("aud")
        if self.auth_settings.require_iat:
            required_claims.append("iat")

        try:
            decoded = jwt.decode(
                token,
                key=signing_key,
                algorithms=[self.auth_settings.algorithms],
                audience=self.auth_settings.audience,
                issuer=self.auth_settings.issuer_url,
                leeway=self.auth_settings.leeway_seconds,
                options={
                    "require": required_claims,
                    "verify_aud": self.auth_settings.audience is not None,
                    "verify_iss": self.auth_settings.issuer_url is not None,
                },
            )
        except ExpiredSignatureError as exc:
            raise UnauthorizedError(detail="Invalid bearer token") from exc
        except (InvalidIssuerError, InvalidAudienceError, InvalidTokenError) as exc:
            raise UnauthorizedError(detail="Invalid bearer token") from exc

        if not isinstance(decoded, dict):
            raise UnauthorizedError(detail="Invalid bearer token")

        self._validate_authorized_party(decoded)
        self._validate_token_lifetime(decoded)
        return decoded

    async def _resolve_signing_key(self, header: dict[str, Any]) -> Any:
        jwks = await self._get_jwks()
        key = self._resolve_signing_key_from_jwks(jwks, header)
        if key is not None:
            return key

        refreshed_jwks = await self._refresh_jwks_after_kid_miss()
        if refreshed_jwks is not None:
            refreshed_key = self._resolve_signing_key_from_jwks(refreshed_jwks, header)
            if refreshed_key is not None:
                return refreshed_key

        raise UnauthorizedError(detail="Invalid bearer token")

    async def _get_jwks(self) -> dict[str, Any]:
        if self._jwks_cache and self._jwks_cache.expires_at > time.time():
            return self._jwks_cache.value

        return await self._fetch_and_cache_jwks()

    async def _fetch_and_cache_jwks(self) -> dict[str, Any]:
        jwks_url = await self._resolve_jwks_url()
        jwks = await self._fetch_json_async(jwks_url)
        self._validate_jwks_payload(jwks)
        self._jwks_cache = _CacheEntry(
            value=jwks,
            expires_at=time.time() + self.auth_settings.jwks_cache_ttl_seconds,
        )
        return jwks

    async def _refresh_jwks_after_kid_miss(self) -> dict[str, Any] | None:
        now = time.monotonic()
        cooldown = self.auth_settings.jwks_refresh_cooldown_seconds
        if now - self._last_forced_jwks_refresh_at < cooldown:
            return self._jwks_cache.value if self._jwks_cache else None

        try:
            await asyncio.wait_for(
                self._jwks_refresh_lock.acquire(),
                timeout=self.auth_settings.jwks_refresh_lock_timeout_seconds,
            )
        except TimeoutError:
            return self._jwks_cache.value if self._jwks_cache else None

        try:
            now = time.monotonic()
            if now - self._last_forced_jwks_refresh_at < cooldown:
                return self._jwks_cache.value if self._jwks_cache else None

            self._last_forced_jwks_refresh_at = now
            try:
                return await self._fetch_and_cache_jwks()
            except UnauthorizedError:
                return self._jwks_cache.value if self._jwks_cache else None
        finally:
            self._jwks_refresh_lock.release()

    async def _resolve_jwks_url(self) -> str:
        jwks_url = self.auth_settings.jwks_url
        if jwks_url is not None:
            return jwks_url

        discovery = await self._get_discovery_document()
        jwks_uri = discovery.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri:
            raise UnauthorizedError(detail="Invalid identity metadata")
        return jwks_uri

    async def _get_discovery_document(self) -> dict[str, Any]:
        if self._discovery_cache and self._discovery_cache.expires_at > time.time():
            return self._discovery_cache.value

        if not self.auth_settings.issuer_url:
            raise UnauthorizedError(detail="Invalid authentication configuration")

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
        keys = self._validate_jwks_payload(jwks)

        for jwk in keys:
            if isinstance(jwk, dict) and jwk.get("kid") == kid:
                return self._public_key_from_jwk(jwk)

        return None

    def _validate_jwks_payload(self, jwks: dict[str, Any]) -> list[Any]:
        keys = jwks.get("keys")
        if not isinstance(keys, list) or not keys:
            raise UnauthorizedError(detail="Invalid identity metadata")
        return keys

    def _public_key_from_jwk(self, jwk: dict[str, Any]) -> Any:
        kty = jwk.get("kty")
        algorithm_loader = get_default_algorithms().get("RS256")

        if kty != "RSA" or algorithm_loader is None:
            raise UnauthorizedError(detail="Invalid identity metadata")

        try:
            return algorithm_loader.from_jwk(json.dumps(jwk))
        except Exception as exc:
            raise UnauthorizedError(detail="Invalid identity metadata") from exc

    def _validate_authorized_party(self, decoded: dict[str, Any]) -> None:
        allowed_parties = self.auth_settings.allowed_authorized_parties
        if not allowed_parties:
            return

        azp = decoded.get("azp")
        if not isinstance(azp, str) or azp not in allowed_parties:
            raise UnauthorizedError(detail="Invalid bearer token")

    def _validate_token_lifetime(self, decoded: dict[str, Any]) -> None:
        exp = decoded.get("exp")
        iat = decoded.get("iat")

        if self.auth_settings.require_iat and not isinstance(iat, int):
            raise UnauthorizedError(detail="Invalid bearer token")
        if not isinstance(exp, int):
            raise UnauthorizedError(detail="Invalid bearer token")
        if not isinstance(iat, int):
            return

        lifetime = exp - iat
        if lifetime < 0 or lifetime > self.auth_settings.max_token_lifetime_seconds:
            raise UnauthorizedError(detail="Invalid bearer token")

    async def _fetch_json_async(self, url: str) -> dict[str, Any]:
        try:
            result = await asyncio.to_thread(self._fetch_json, url)
        except UnauthorizedError:
            raise
        except Exception as exc:
            raise UnauthorizedError(detail="Unable to fetch identity metadata") from exc

        if not isinstance(result, dict):
            raise UnauthorizedError(detail="Invalid identity metadata")

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
        tuple(settings.auth.allowed_authorized_parties),
        settings.auth.jwks_url,
        settings.auth.algorithms,
        settings.auth.leeway_seconds,
        settings.auth.discovery_cache_ttl_seconds,
        settings.auth.jwks_cache_ttl_seconds,
        settings.auth.require_kid,
        settings.auth.require_iat,
        settings.auth.max_token_lifetime_seconds,
        settings.auth.jwks_refresh_cooldown_seconds,
        settings.auth.jwks_refresh_lock_timeout_seconds,
    )


def get_jwt_validator(settings: Settings) -> JwtValidator:
    global _jwt_validator, _jwt_validator_signature

    signature = _validator_signature(settings)
    if _jwt_validator is None or signature != _jwt_validator_signature:
        _jwt_validator = JwtValidator(auth_settings=settings.auth)
        _jwt_validator_signature = signature

    return _jwt_validator

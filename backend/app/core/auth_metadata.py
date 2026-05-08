from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from app.core.auth_jwt import _fetch_json_url
from app.core.config.settings import Settings
from app.core.logging import get_logger

FetchJson = Callable[[str], dict[str, Any]]


async def init_auth_validation(
    settings: Settings,
    *,
    fetch_json: FetchJson | None = None,
) -> None:
    auth = settings.auth
    if not auth.enabled or auth.metadata_validation == "disabled":
        return

    try:
        await _validate_auth_metadata(settings, fetch_json=fetch_json)
    except Exception as exc:
        if auth.metadata_validation == "fail":
            raise RuntimeError("Authentication metadata validation failed") from exc
        get_logger(__name__).warning(
            "auth_metadata_validation_warning",
            reason=exc.__class__.__name__,
        )


async def _validate_auth_metadata(
    settings: Settings,
    *,
    fetch_json: FetchJson | None,
) -> None:
    auth = settings.auth
    if not auth.issuer_url:
        raise ValueError("AUTH__ISSUER_URL is required")

    fetcher = fetch_json or _fetch_json_url
    discovery_url = f"{auth.issuer_url.rstrip('/')}/.well-known/openid-configuration"
    discovery = await _fetch_json(fetcher, discovery_url)
    if not isinstance(discovery, dict):
        raise ValueError("OIDC discovery payload must be an object")

    if discovery.get("issuer") != auth.issuer_url:
        raise ValueError("OIDC discovery issuer does not match configured issuer")

    jwks_uri = auth.jwks_url
    if jwks_uri is None:
        discovered_jwks_uri = discovery.get("jwks_uri")
        if not isinstance(discovered_jwks_uri, str) or not discovered_jwks_uri.strip():
            raise ValueError("OIDC discovery jwks_uri is required")
        jwks_uri = discovered_jwks_uri.strip()

    if settings.app.environment in {"staging", "prod"} and not _is_https(jwks_uri):
        raise ValueError("OIDC JWKS URI must use HTTPS in staging/prod")

    supported_algs = discovery.get("id_token_signing_alg_values_supported")
    if isinstance(supported_algs, list) and "RS256" not in supported_algs:
        raise ValueError("OIDC discovery does not advertise RS256")

    jwks = await _fetch_json(fetcher, jwks_uri)
    _validate_jwks(jwks)


async def _fetch_json(fetcher: FetchJson, url: str) -> dict[str, Any]:
    result = await asyncio.to_thread(fetcher, url)
    if not isinstance(result, dict):
        raise ValueError("Identity metadata payload must be an object")
    return result


def _validate_jwks(jwks: dict[str, Any]) -> None:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("JWKS must contain signing keys")

    rsa_signing_keys = [key for key in keys if _is_rsa_signing_key(key)]
    if not rsa_signing_keys:
        raise ValueError("JWKS must contain an RSA signing key")

    if any(
        not isinstance(key.get("kid"), str) or not key["kid"].strip()
        for key in rsa_signing_keys
    ):
        raise ValueError("JWKS RSA signing keys must contain kid")


def _is_rsa_signing_key(key: object) -> bool:
    if not isinstance(key, dict):
        return False
    if key.get("kty") != "RSA":
        return False
    key_use = key.get("use")
    if key_use is not None and key_use != "sig":
        return False
    alg = key.get("alg")
    if alg is not None and alg != "RS256":
        return False
    return True


def _is_https(url: str) -> bool:
    return urlparse(url).scheme == "https"

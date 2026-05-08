from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.error import URLError
from urllib.request import urlopen

from app.core.config.settings import Settings
from app.core.logging import get_logger

_DISCOVERY_PATH = "/.well-known/openid-configuration"


async def init_auth_validation(
    settings: Settings,
    *,
    fetch_json: Callable[[str], dict[str, Any]] | None = None,
) -> None:
    auth = settings.auth
    if not auth.enabled or auth.metadata_validation == "disabled":
        return

    fetcher = fetch_json or _fetch_json_url

    try:
        await _validate_auth_metadata(settings, fetcher=fetcher)
    except Exception as exc:
        if auth.metadata_validation == "fail":
            raise RuntimeError("OIDC metadata validation failed") from exc

        log = get_logger(__name__)
        log.warning(
            "oidc_metadata_validation_warning",
            auth_metadata_validation_mode=auth.metadata_validation,
            error_type=type(exc).__name__,
        )


async def _validate_auth_metadata(
    settings: Settings,
    *,
    fetcher: Callable[[str], dict[str, Any]],
) -> None:
    auth = settings.auth
    issuer = auth.issuer_url
    if not issuer:
        raise ValueError("AUTH__ISSUER_URL is required for metadata validation")

    discovery_url = f"{issuer.rstrip('/')}{_DISCOVERY_PATH}"
    discovery = await _fetch_json_async(fetcher, discovery_url)
    if not isinstance(discovery, dict):
        raise ValueError("OIDC discovery payload must be an object")

    if discovery.get("issuer") != issuer:
        raise ValueError("OIDC discovery issuer does not match AUTH__ISSUER_URL")

    jwks_url = auth.jwks_url
    if not jwks_url:
        jwks_uri = discovery.get("jwks_uri")
        if not isinstance(jwks_uri, str) or not jwks_uri.strip():
            raise ValueError("OIDC discovery jwks_uri is required")
        jwks_url = jwks_uri.strip()

    if settings.app.environment in {"staging", "prod"} and not jwks_url.startswith(
        "https://"
    ):
        raise ValueError("OIDC JWKS URI must use HTTPS in staging/prod")

    supported_algs = discovery.get("id_token_signing_alg_values_supported")
    if supported_algs is not None and (
        not isinstance(supported_algs, list) or "RS256" not in supported_algs
    ):
        raise ValueError("OIDC discovery does not advertise RS256 support")

    jwks = await _fetch_json_async(fetcher, jwks_url)
    _validate_jwks(jwks)


def _validate_jwks(jwks: dict[str, Any]) -> None:
    if not isinstance(jwks, dict):
        raise ValueError("JWKS payload must be an object")

    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise ValueError("JWKS must contain signing keys")

    rsa_signing_keys = [
        key
        for key in keys
        if isinstance(key, dict)
        and key.get("kty") == "RSA"
        and key.get("use", "sig") == "sig"
    ]
    if not rsa_signing_keys:
        raise ValueError("JWKS must contain an RSA signing key")

    if any(
        not isinstance(key.get("kid"), str) or not key.get("kid")
        for key in rsa_signing_keys
    ):
        raise ValueError("JWKS RSA signing keys must include kid")


async def _fetch_json_async(
    fetcher: Callable[[str], dict[str, Any]],
    url: str,
) -> dict[str, Any]:
    return await asyncio.to_thread(fetcher, url)


def _fetch_json_url(url: str) -> dict[str, Any]:
    try:
        with urlopen(url, timeout=5) as response:
            payload = response.read().decode("utf-8")
            result = json.loads(payload)
    except (URLError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to fetch identity metadata") from exc

    if not isinstance(result, dict):
        raise ValueError("Identity metadata payload is invalid")
    return result

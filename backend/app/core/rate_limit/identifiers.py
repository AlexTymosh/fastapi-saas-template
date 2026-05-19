from __future__ import annotations

import hmac
import ipaddress
from dataclasses import dataclass
from hashlib import sha256

from fastapi import Request
from pydantic import SecretStr

from app.core.auth import AuthenticatedPrincipal

BUCKET_KEY_PREFIX = "rlid:v1:hmac-sha256"


@dataclass(frozen=True)
class RateLimitIdentifier:
    kind: str
    bucket_key: str


@dataclass(frozen=True)
class RateLimitBucket:
    kind: str
    raw_value: str


def build_bucket_identifier(
    *,
    bucket: RateLimitBucket,
    identifier_secret: SecretStr | str,
) -> RateLimitIdentifier:
    return RateLimitIdentifier(
        kind=bucket.kind,
        bucket_key=_build_bucket_key(
            message=f"{bucket.kind}:{bucket.raw_value}",
            secret=_secret_value(identifier_secret),
        ),
    )


def build_identifier(
    *,
    principal: AuthenticatedPrincipal | None,
    request: Request,
    trust_proxy_headers: bool,
    identifier_secret: SecretStr | str,
    trusted_proxy_cidrs: list[str] | tuple[str, ...] | None = None,
) -> RateLimitIdentifier:
    secret = _secret_value(identifier_secret)
    if principal is not None:
        return RateLimitIdentifier(
            kind="user",
            bucket_key=_build_bucket_key(
                message=f"user:{principal.external_auth_id}",
                secret=secret,
            ),
        )

    ip_value = resolve_client_ip(
        request=request,
        trust_proxy_headers=trust_proxy_headers,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    )
    return RateLimitIdentifier(
        kind="ip",
        bucket_key=_build_bucket_key(message=f"ip:{ip_value}", secret=secret),
    )


def resolve_client_ip(
    *,
    request: Request,
    trust_proxy_headers: bool,
    trusted_proxy_cidrs: list[str] | tuple[str, ...] | None = None,
) -> str:
    peer_ip = _normalise_ip(request.client.host if request.client else None)
    if not trust_proxy_headers:
        return peer_ip

    if not is_request_from_trusted_proxy(
        request=request,
        trusted_proxy_cidrs=trusted_proxy_cidrs,
    ):
        return peer_ip

    x_forwarded_for = request.headers.get("x-forwarded-for")
    if x_forwarded_for:
        first_hop = x_forwarded_for.split(",", maxsplit=1)[0].strip()
        normalised_first_hop = _normalise_ip(first_hop)
        if normalised_first_hop != "0.0.0.0":
            return normalised_first_hop

    x_real_ip = request.headers.get("x-real-ip")
    if x_real_ip:
        normalised_real_ip = _normalise_ip(x_real_ip.strip())
        if normalised_real_ip != "0.0.0.0":
            return normalised_real_ip

    return peer_ip


def is_request_from_trusted_proxy(
    *,
    request: Request,
    trusted_proxy_cidrs: list[str] | tuple[str, ...] | None,
) -> bool:
    peer = _parse_ip(request.client.host if request.client else None)
    if peer is None:
        return False

    for raw_cidr in trusted_proxy_cidrs or []:
        try:
            network = ipaddress.ip_network(raw_cidr, strict=False)
        except ValueError:
            continue
        if peer in network:
            return True
    return False


def _parse_ip(
    value: str | None,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = (value or "").strip()
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _normalise_ip(value: str | None) -> str:
    parsed = _parse_ip(value)
    if parsed is None:
        return "0.0.0.0"

    if parsed.version == 6:
        network = ipaddress.ip_network(f"{parsed}/64", strict=False)
        return network.network_address.compressed

    return parsed.compressed


def _secret_value(secret: SecretStr | str) -> str:
    if isinstance(secret, SecretStr):
        return secret.get_secret_value()
    return secret


def _build_bucket_key(*, message: str, secret: str) -> str:
    digest = hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        sha256,
    ).hexdigest()
    return f"{BUCKET_KEY_PREFIX}:{digest}"

from __future__ import annotations

import hmac
import ipaddress
from hashlib import sha256

from pydantic import SecretStr

_AUDIT_IP_HMAC_PREFIX = "hmac:v1"


def minimise_ip_address(
    value: str | None,
    *,
    secret: SecretStr | str | None = None,
) -> str | None:
    """Return an audit-safe network identifier instead of the raw client IP.

    If a secret is configured, store a stable truncated HMAC for correlation.
    Without a secret, fall back to coarse network minimisation: IPv4 /24 and
    IPv6 /64. Invalid input is discarded instead of persisted.
    """

    parsed = _parse_ip(value)
    if parsed is None:
        return None

    secret_value = _secret_value(secret)
    if secret_value:
        digest = hmac.new(
            secret_value.encode("utf-8"),
            parsed.compressed.encode("utf-8"),
            sha256,
        ).hexdigest()[:32]
        return f"{_AUDIT_IP_HMAC_PREFIX}:{digest}"

    if parsed.version == 4:
        network = ipaddress.ip_network(f"{parsed}/24", strict=False)
    else:
        network = ipaddress.ip_network(f"{parsed}/64", strict=False)

    return f"{network.network_address.compressed}/{network.prefixlen}"


def normalise_user_agent(value: str | None) -> str | None:
    """Store only a coarse user-agent family for audit correlation.

    Full user-agent strings can identify a browser/device fingerprint. Audit
    events only need broad client family data unless a separate short-retention
    security log explicitly keeps raw request metadata.
    """

    if value is None:
        return None

    normalised = " ".join(value.strip().split())
    if not normalised:
        return None

    lowered = normalised.lower()
    if "pytest" in lowered:
        return "client:test"
    if "curl/" in lowered:
        return "client:curl"
    if "python-requests" in lowered or "httpx" in lowered or "aiohttp" in lowered:
        return "client:http-library"
    if "googlebot" in lowered or "bingbot" in lowered or "bot" in lowered:
        return "client:bot"
    if "edg/" in lowered:
        return "browser:edge"
    if "firefox/" in lowered:
        return "browser:firefox"
    if "chrome/" in lowered or "chromium/" in lowered:
        return "browser:chrome"
    if "safari/" in lowered:
        return "browser:safari"
    if "java/" in lowered:
        return "client:java"

    return "client:other"


def _parse_ip(
    value: str | None,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    candidate = (value or "").strip()
    try:
        return ipaddress.ip_address(candidate)
    except ValueError:
        return None


def _secret_value(secret: SecretStr | str | None) -> str | None:
    if secret is None:
        return None
    if isinstance(secret, SecretStr):
        value = secret.get_secret_value()
    else:
        value = str(secret)
    value = value.strip()
    return value or None

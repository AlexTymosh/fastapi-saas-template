from __future__ import annotations

from starlette.requests import Request

from app.core.auth import AuthenticatedPrincipal
from app.core.rate_limit.identifiers import build_identifier, resolve_client_ip

SECRET = "test-rate-limit-identifier-secret-32-bytes"
OTHER_SECRET = "other-rate-limit-identifier-secret-32-bytes"
PREFIX = "rlid:v1:hmac-sha256:"


def _request(
    *,
    client_host: str = "203.0.113.10",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": headers or [],
            "client": (client_host, 12345),
            "server": ("testserver", 80),
            "scheme": "http",
        }
    )


def _principal(external_auth_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
        email="user@example.com",
        email_verified=True,
    )


def test_same_user_and_secret_produce_stable_bucket_key() -> None:
    request = _request()

    first = build_identifier(
        principal=_principal("kc-user-123"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )
    second = build_identifier(
        principal=_principal("kc-user-123"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )

    assert first.kind == "user"
    assert first.bucket_key == second.bucket_key
    assert first.bucket_key.startswith(PREFIX)


def test_same_user_with_different_secret_produces_different_bucket_key() -> None:
    request = _request()

    first = build_identifier(
        principal=_principal("kc-user-123"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )
    second = build_identifier(
        principal=_principal("kc-user-123"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=OTHER_SECRET,
    )

    assert first.bucket_key != second.bucket_key


def test_raw_user_and_ip_values_are_not_exposed_in_bucket_keys() -> None:
    external_auth_id = "kc-raw-user-value"
    ip_address = "198.51.100.44"

    user_identifier = build_identifier(
        principal=_principal(external_auth_id),
        request=_request(client_host=ip_address),
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )
    ip_identifier = build_identifier(
        principal=None,
        request=_request(client_host=ip_address),
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )

    assert external_auth_id not in user_identifier.bucket_key
    assert ip_address not in ip_identifier.bucket_key
    assert user_identifier.bucket_key.startswith(PREFIX)
    assert ip_identifier.bucket_key.startswith(PREFIX)


def test_user_and_ip_domain_separation_prevents_digest_reuse() -> None:
    same_value = "203.0.113.77"

    user_identifier = build_identifier(
        principal=_principal(same_value),
        request=_request(client_host="192.0.2.10"),
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )
    ip_identifier = build_identifier(
        principal=None,
        request=_request(client_host=same_value),
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )

    assert user_identifier.bucket_key != ip_identifier.bucket_key


def test_invalid_ip_falls_back_without_raising() -> None:
    identifier = build_identifier(
        principal=None,
        request=_request(client_host="not-an-ip-address"),
        trust_proxy_headers=False,
        identifier_secret=SECRET,
    )

    assert identifier.kind == "ip"
    assert identifier.bucket_key.startswith(PREFIX)


def test_trusted_proxy_ipv6_is_normalised_to_canonical_compressed_form() -> None:
    request = _request(
        client_host="192.0.2.10",
        headers=[(b"x-forwarded-for", b"2001:0db8:0000:0000:0000:ff00:0042:8329")],
    )

    assert (
        resolve_client_ip(request=request, trust_proxy_headers=True)
        == "2001:db8::ff00:42:8329"
    )

from __future__ import annotations

from starlette.requests import Request

from app.core.auth import AuthenticatedPrincipal
from app.core.rate_limit.identifiers import (
    BUCKET_KEY_PREFIX,
    build_identifier,
    resolve_client_ip,
)

SECRET_A = "a" * 32
SECRET_B = "b" * 32


def _request(
    *, host: str = "203.0.113.10", headers: dict[str, str] | None = None
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [
                (name.lower().encode("latin-1"), value.encode("latin-1"))
                for name, value in (headers or {}).items()
            ],
            "client": (host, 12345),
        }
    )


def _principal(external_auth_id: str) -> AuthenticatedPrincipal:
    return AuthenticatedPrincipal(
        external_auth_id=external_auth_id,
        email="user@example.com",
        email_verified=True,
    )


def test_same_user_and_secret_build_same_bucket_key() -> None:
    request = _request()

    first = build_identifier(
        principal=_principal("kc-user-1"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )
    second = build_identifier(
        principal=_principal("kc-user-1"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )

    assert first.bucket_key == second.bucket_key


def test_same_user_with_different_secret_builds_different_bucket_key() -> None:
    request = _request()

    first = build_identifier(
        principal=_principal("kc-user-1"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )
    second = build_identifier(
        principal=_principal("kc-user-1"),
        request=request,
        trust_proxy_headers=False,
        identifier_secret=SECRET_B,
    )

    assert first.bucket_key != second.bucket_key


def test_bucket_key_hides_raw_user_and_ip_values() -> None:
    raw_user = "kc-sensitive-user"
    raw_ip = "198.51.100.42"

    user_identifier = build_identifier(
        principal=_principal(raw_user),
        request=_request(host=raw_ip),
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )
    ip_identifier = build_identifier(
        principal=None,
        request=_request(host=raw_ip),
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )

    assert raw_user not in user_identifier.bucket_key
    assert raw_ip not in ip_identifier.bucket_key


def test_user_and_ip_domains_are_separated() -> None:
    shared_value = "203.0.113.77"

    user_identifier = build_identifier(
        principal=_principal(shared_value),
        request=_request(host="192.0.2.1"),
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )
    ip_identifier = build_identifier(
        principal=None,
        request=_request(host=shared_value),
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )

    assert user_identifier.bucket_key != ip_identifier.bucket_key


def test_bucket_key_has_versioned_hmac_prefix() -> None:
    identifier = build_identifier(
        principal=_principal("kc-user-1"),
        request=_request(),
        trust_proxy_headers=False,
        identifier_secret=SECRET_A,
    )

    assert identifier.bucket_key.startswith(f"{BUCKET_KEY_PREFIX}:")


def test_invalid_ip_falls_back_without_error() -> None:
    assert (
        resolve_client_ip(request=_request(host="not-an-ip"), trust_proxy_headers=False)
        == "0.0.0.0"
    )


def test_ipv6_is_normalised_to_canonical_compressed_form() -> None:
    request = _request(host="2001:0db8:0000:0000:0000:0000:0000:0001")

    assert (
        resolve_client_ip(request=request, trust_proxy_headers=False) == "2001:db8::1"
    )


def test_trusted_proxy_headers_are_normalised() -> None:
    request = _request(
        host="198.51.100.1",
        headers={"X-Forwarded-For": "2001:0db8:0000:0000::0002, 198.51.100.2"},
    )

    assert resolve_client_ip(request=request, trust_proxy_headers=True) == "2001:db8::2"

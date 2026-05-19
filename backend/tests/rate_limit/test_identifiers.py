from __future__ import annotations

from starlette.requests import Request

from app.core.auth import AuthenticatedPrincipal
from app.core.rate_limit.identifiers import (
    BUCKET_KEY_PREFIX,
    build_identifier,
    is_request_from_trusted_proxy,
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


def test_ipv6_is_normalised_to_64_network_for_ip_buckets() -> None:
    first = _request(host="2001:0db8:0000:0000:0000:0000:0000:0001")
    second = _request(host="2001:0db8:0000:0000:0000:0000:0000:ffff")

    assert resolve_client_ip(request=first, trust_proxy_headers=False) == "2001:db8::"
    assert resolve_client_ip(request=second, trust_proxy_headers=False) == "2001:db8::"


def test_direct_client_spoofed_forwarded_header_is_ignored() -> None:
    request = _request(
        host="203.0.113.10",
        headers={"X-Forwarded-For": "198.51.100.77"},
    )

    assert (
        resolve_client_ip(
            request=request,
            trust_proxy_headers=True,
            trusted_proxy_cidrs=["10.0.0.0/8"],
        )
        == "203.0.113.10"
    )


def test_trusted_proxy_headers_are_normalised_when_peer_is_trusted() -> None:
    request = _request(
        host="10.1.2.3",
        headers={"X-Forwarded-For": "2001:0db8:0000:0000::0002, 198.51.100.2"},
    )

    assert (
        resolve_client_ip(
            request=request,
            trust_proxy_headers=True,
            trusted_proxy_cidrs=["10.0.0.0/8"],
        )
        == "2001:db8::"
    )


def test_malformed_forwarded_headers_fall_back_to_trusted_proxy_peer() -> None:
    request = _request(
        host="10.1.2.3",
        headers={"X-Forwarded-For": "not-an-ip", "X-Real-IP": "also-not-an-ip"},
    )

    assert (
        resolve_client_ip(
            request=request,
            trust_proxy_headers=True,
            trusted_proxy_cidrs=["10.0.0.0/8"],
        )
        == "10.1.2.3"
    )


def test_trusted_proxy_detection_requires_peer_cidr_match() -> None:
    trusted = _request(host="10.1.2.3")
    untrusted = _request(host="203.0.113.10")

    assert is_request_from_trusted_proxy(
        request=trusted, trusted_proxy_cidrs=["10.0.0.0/8"]
    )
    assert not is_request_from_trusted_proxy(
        request=untrusted, trusted_proxy_cidrs=["10.0.0.0/8"]
    )


def test_same_business_bucket_and_secret_build_same_bucket_key() -> None:
    from app.core.rate_limit.identifiers import RateLimitBucket, build_bucket_identifier

    bucket = RateLimitBucket(
        kind="organisation_target_email",
        raw_value=(
            "organisation:00000000-0000-4000-8000-000000000001"
            ":email:invitee@example.com"
        ),
    )

    first = build_bucket_identifier(bucket=bucket, identifier_secret=SECRET_A)
    second = build_bucket_identifier(bucket=bucket, identifier_secret=SECRET_A)

    assert first.bucket_key == second.bucket_key
    assert first.kind == "organisation_target_email"


def test_business_bucket_kind_raw_value_and_secret_are_domain_separated() -> None:
    from app.core.rate_limit.identifiers import RateLimitBucket, build_bucket_identifier

    raw_value = "organisation:00000000-0000-4000-8000-000000000001"
    organisation = build_bucket_identifier(
        bucket=RateLimitBucket(kind="organisation", raw_value=raw_value),
        identifier_secret=SECRET_A,
    )
    invite = build_bucket_identifier(
        bucket=RateLimitBucket(kind="invite", raw_value=raw_value),
        identifier_secret=SECRET_A,
    )
    other_raw = build_bucket_identifier(
        bucket=RateLimitBucket(kind="organisation", raw_value=f"{raw_value}:different"),
        identifier_secret=SECRET_A,
    )
    other_secret = build_bucket_identifier(
        bucket=RateLimitBucket(kind="organisation", raw_value=raw_value),
        identifier_secret=SECRET_B,
    )

    assert organisation.bucket_key != invite.bucket_key
    assert organisation.bucket_key != other_raw.bucket_key
    assert organisation.bucket_key != other_secret.bucket_key


def test_business_bucket_key_hides_raw_email_domain_organisation_and_invite() -> None:
    from app.core.rate_limit.identifiers import RateLimitBucket, build_bucket_identifier

    organisation_id = "00000000-0000-4000-8000-000000000001"
    invite_id = "00000000-0000-4000-8000-000000000002"
    email = "invitee@example.com"
    domain = "example.com"
    identifier = build_bucket_identifier(
        bucket=RateLimitBucket(
            kind="organisation_target_email",
            raw_value=(
                f"organisation:{organisation_id}:invite:{invite_id}:email:{email}"
            ),
        ),
        identifier_secret=SECRET_A,
    )

    assert identifier.bucket_key.startswith(f"{BUCKET_KEY_PREFIX}:")
    assert email not in identifier.bucket_key
    assert domain not in identifier.bucket_key
    assert organisation_id not in identifier.bucket_key
    assert invite_id not in identifier.bucket_key

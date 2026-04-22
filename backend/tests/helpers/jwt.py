from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa


def _to_base64url(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def generate_rsa_jwk(
    *,
    kid: str = "test-kid",
) -> tuple[dict[str, str], rsa.RSAPrivateKey]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_numbers = private_key.public_key().public_numbers()

    jwk = {
        "kty": "RSA",
        "kid": kid,
        "use": "sig",
        "alg": "RS256",
        "n": _to_base64url(public_numbers.n),
        "e": _to_base64url(public_numbers.e),
    }
    return jwk, private_key


def issue_access_token(
    *,
    private_key: rsa.RSAPrivateKey,
    kid: str,
    issuer: str,
    audience: str,
    subject: str,
    claims: dict[str, object] | None = None,
    expires_in_seconds: int = 300,
) -> str:
    now = datetime.now(UTC)
    payload: dict[str, object] = {
        "iss": issuer,
        "aud": audience,
        "sub": subject,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in_seconds)).timestamp()),
    }
    if claims:
        payload.update(claims)

    return jwt.encode(
        payload,
        key=private_key,
        algorithm="RS256",
        headers={"kid": kid},
    )

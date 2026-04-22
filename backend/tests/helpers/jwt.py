from __future__ import annotations

import base64
import hashlib
import json
import random
from dataclasses import dataclass

_SHA256_DER_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


@dataclass(frozen=True)
class RsaKeypair:
    n: int
    e: int
    d: int


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_uint(value: int) -> str:
    raw = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return _b64url_encode(raw)


def _is_probable_prime(value: int, rounds: int = 8) -> bool:
    if value < 2:
        return False
    for small in (2, 3, 5, 7, 11, 13, 17, 19, 23, 29):
        if value % small == 0:
            return value == small

    d = value - 1
    s = 0
    while d % 2 == 0:
        d //= 2
        s += 1

    for _ in range(rounds):
        a = random.randrange(2, value - 2)
        x = pow(a, d, value)
        if x in (1, value - 1):
            continue
        for _ in range(s - 1):
            x = pow(x, 2, value)
            if x == value - 1:
                break
        else:
            return False

    return True


def _generate_prime(bits: int) -> int:
    while True:
        candidate = random.getrandbits(bits) | 1 | (1 << (bits - 1))
        if _is_probable_prime(candidate):
            return candidate


def generate_rsa_keypair(bits: int = 1024) -> RsaKeypair:
    public_exponent = 65537
    while True:
        p = _generate_prime(bits // 2)
        q = _generate_prime(bits // 2)
        if p == q:
            continue
        phi = (p - 1) * (q - 1)
        if phi % public_exponent == 0:
            continue
        n = p * q
        d = pow(public_exponent, -1, phi)
        return RsaKeypair(n=n, e=public_exponent, d=d)


def to_jwk(keypair: RsaKeypair, *, kid: str) -> dict[str, str]:
    return {
        "kty": "RSA",
        "use": "sig",
        "alg": "RS256",
        "kid": kid,
        "n": _b64url_uint(keypair.n),
        "e": _b64url_uint(keypair.e),
    }


def encode_rs256_jwt(
    keypair: RsaKeypair,
    *,
    kid: str,
    claims: dict[str, object],
) -> str:
    header = {"alg": "RS256", "typ": "JWT", "kid": kid}
    header_segment = _b64url_encode(
        json.dumps(header, separators=(",", ":")).encode("utf-8")
    )
    payload_segment = _b64url_encode(
        json.dumps(claims, separators=(",", ":")).encode("utf-8")
    )

    signing_input = f"{header_segment}.{payload_segment}".encode()
    digest = hashlib.sha256(signing_input).digest()
    digest_info = _SHA256_DER_PREFIX + digest

    key_size_bytes = (keypair.n.bit_length() + 7) // 8
    padding_length = key_size_bytes - len(digest_info) - 3
    if padding_length < 8:
        raise ValueError("RSA key is too small for RS256")

    encoded_message = (
        b"\x00\x01" + (b"\xff" * padding_length) + b"\x00" + digest_info
    )
    message_int = int.from_bytes(encoded_message, "big")
    signature_int = pow(message_int, keypair.d, keypair.n)
    signature = signature_int.to_bytes(key_size_bytes, "big")
    signature_segment = _b64url_encode(signature)

    return f"{header_segment}.{payload_segment}.{signature_segment}"

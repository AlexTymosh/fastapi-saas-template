from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from structlog.typing import EventDict

from app.core.context import get_request_id

_EMAIL_RE = re.compile(r"(?P<name>[^@\s]+)@(?P<domain>[^@\s]+\.[^@\s]+)")
_CAMEL_CASE_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_JWT_COMPACT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\.[A-Za-z0-9_-]{5,}\b"
)

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "access_token",
    "api_key",
    "apikey",
    "auth_header",
    "authorization",
    "authorization_header",
    "client_secret",
    "cookie",
    "csrf",
    "encrypted_raw_token",
    "id_token",
    "password",
    "private_key",
    "raw_token",
    "refresh_token",
    "secret",
    "session",
    "set_cookie",
    "token",
    "token_hash",
}
_SENSITIVE_MARKERS = {
    "access_token",
    "api_key",
    "apikey",
    "auth_header",
    "authorization",
    "authorization_header",
    "client_secret",
    "cookie",
    "csrf",
    "encrypted_raw_token",
    "id_token",
    "password",
    "private_key",
    "raw_token",
    "refresh_token",
    "secret",
    "session",
    "set_cookie",
    "token",
    "token_hash",
}


def add_request_id(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    request_id = get_request_id()
    if request_id and "request_id" not in event_dict:
        event_dict["request_id"] = request_id
    return event_dict


def add_service_context(
    service_name: str,
    environment: str,
    version: str,
):
    def processor(
        logger: Any,
        method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        event_dict.setdefault("service", service_name)
        event_dict.setdefault("environment", environment)
        event_dict.setdefault("version", version)
        return event_dict

    return processor


def ensure_category(
    default_category: str = "application",
):
    def processor(
        logger: Any,
        method_name: str,
        event_dict: EventDict,
    ) -> EventDict:
        event_dict.setdefault("category", default_category)
        return event_dict

    return processor


def drop_none_values(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    return {key: value for key, value in event_dict.items() if value is not None}


def redact_sensitive_fields(
    logger: Any,
    method_name: str,
    event_dict: EventDict,
) -> EventDict:
    return _sanitize_mapping(event_dict)


def _sanitize_mapping(data: Mapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in data.items():
        if _is_sensitive_key(key):
            result[key] = _REDACTED
            continue

        result[key] = _sanitize_value(value)

    return result


def _is_sensitive_key(key: Any) -> bool:
    normalised_key = _normalise_key(key)
    return normalised_key in _SENSITIVE_KEYS or any(
        marker in normalised_key for marker in _SENSITIVE_MARKERS
    )


def _normalise_key(key: Any) -> str:
    camel_split = _CAMEL_CASE_BOUNDARY_RE.sub("_", str(key))
    return camel_split.lower().replace("-", "_").replace(".", "_")


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)

    if isinstance(value, str):
        lowered = value.lower()
        if "bearer " in lowered or "basic " in lowered or _JWT_COMPACT_RE.search(value):
            return _REDACTED

        if "@" in value:
            return _mask_email(value)

        return value

    return value


def _mask_email(value: str) -> str:
    match = _EMAIL_RE.fullmatch(value.strip())
    if not match:
        return value

    name = match.group("name")
    domain = match.group("domain")

    if len(name) <= 2:
        masked_name = "*" * len(name)
    else:
        masked_name = f"{name[0]}***{name[-1]}"

    return f"{masked_name}@{domain}"

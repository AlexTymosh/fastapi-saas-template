from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from structlog.typing import EventDict

from app.core.context import get_request_id

_EMAIL_RE = re.compile(r"(?P<name>[^@\s]+)@(?P<domain>[^@\s]+\.[^@\s]+)")
_CAMEL_CASE_BOUNDARY_RE = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_KEY_SEPARATOR_RE = re.compile(r"[^a-z0-9]+")
_AUTH_HEADER_VALUE_RE = re.compile(r"\b(?:bearer|basic)\s+", re.IGNORECASE)
_JWT_COMPACT_RE = re.compile(
    r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"
)

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "id_token",
    "authorization",
    "cookie",
    "set_cookie",
    "secret",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "raw_token",
    "token_hash",
    "encrypted_raw_token",
    "session",
    "csrf",
}
_SENSITIVE_KEY_MARKERS = {
    "token",
    "password",
    "secret",
    "authorization",
    "cookie",
    "api_key",
    "apikey",
    "client_secret",
    "private_key",
    "access_token",
    "refresh_token",
    "id_token",
    "raw_token",
    "token_hash",
    "encrypted_raw_token",
    "set_cookie",
    "session",
    "csrf",
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


def _is_sensitive_key(key: object) -> bool:
    if not isinstance(key, str):
        return False

    normalized_key = _normalize_log_key(key)
    if normalized_key in _SENSITIVE_KEYS:
        return True

    compact_key = normalized_key.replace("_", "")
    return any(
        marker in normalized_key or marker.replace("_", "") in compact_key
        for marker in _SENSITIVE_KEY_MARKERS
    )


def _normalize_log_key(key: str) -> str:
    separated = _CAMEL_CASE_BOUNDARY_RE.sub("_", key)
    normalized = _KEY_SEPARATOR_RE.sub("_", separated.lower()).strip("_")
    return normalized


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)

    if isinstance(value, str):
        if _is_sensitive_string_value(value):
            return _REDACTED

        if "@" in value:
            return _mask_email(value)

        return value

    return value


def _is_sensitive_string_value(value: str) -> bool:
    return bool(_AUTH_HEADER_VALUE_RE.search(value) or _JWT_COMPACT_RE.search(value))


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

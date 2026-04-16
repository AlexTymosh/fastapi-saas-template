from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from structlog.typing import EventDict

from app.core.context import get_request_id

_EMAIL_RE = re.compile(r"(?P<name>[^@\s]+)@(?P<domain>[^@\s]+\.[^@\s]+)")

_REDACTED = "[REDACTED]"
_SENSITIVE_KEYS = {
    "password",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "secret",
    "api_key",
    "client_secret",
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
        lowered = key.lower()

        if lowered in _SENSITIVE_KEYS:
            result[key] = _REDACTED
            continue

        result[key] = _sanitize_value(value)

    return result


def _sanitize_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _sanitize_mapping(value)

    if isinstance(value, list):
        return [_sanitize_value(item) for item in value]

    if isinstance(value, tuple):
        return tuple(_sanitize_value(item) for item in value)

    if isinstance(value, str):
        if "bearer " in value.lower():
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

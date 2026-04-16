from __future__ import annotations

import re
from collections.abc import MutableMapping
from typing import Any

from structlog.typing import EventDict

from app.core.context import get_request_id

_EMAIL_RE = re.compile(r"(?P<name>[^@\s]+)@(?P<domain>[^@\s]+\.[^@\s]+)")


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
    redacted_keys = {
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

    for key in list(event_dict.keys()):
        lowered = key.lower()
        if lowered in redacted_keys:
            event_dict[key] = "[REDACTED]"
            continue

        value = event_dict[key]

        if isinstance(value, str):
            if "bearer " in value.lower():
                event_dict[key] = "[REDACTED]"
            elif "@" in value:
                event_dict[key] = _mask_email(value)

        elif isinstance(value, MutableMapping):
            event_dict[key] = _redact_mapping(value)

    return event_dict


def _redact_mapping(data: MutableMapping[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}

    for key, value in data.items():
        lowered = key.lower()
        if lowered in {
            "password",
            "token",
            "access_token",
            "refresh_token",
            "authorization",
            "cookie",
            "secret",
            "api_key",
            "client_secret",
        }:
            result[key] = "[REDACTED]"
        elif isinstance(value, str) and "@" in value:
            result[key] = _mask_email(value)
        else:
            result[key] = value

    return result


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

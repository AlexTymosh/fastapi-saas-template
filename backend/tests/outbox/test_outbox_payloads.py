from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.outbox.schemas.payloads import parse_invite_outbox_payload


@pytest.mark.parametrize(
    "payload",
    [
        None,
        [],
        "not-a-json-object",
        123,
        True,
    ],
)
def test_parse_invite_outbox_payload_rejects_non_mapping_payload(
    payload: object,
) -> None:
    with pytest.raises(ValidationError):
        parse_invite_outbox_payload(payload)  # type: ignore[arg-type]

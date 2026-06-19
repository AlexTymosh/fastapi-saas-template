from pathlib import Path

from app.platform.schemas.platform_organisations import (
    PlatformLimitedOrganisationResponse,
)

DOC_PATH = (
    Path(__file__).parents[2]
    / "docs"
    / "access-control"
    / "en"
    / "platform-access.en.md"
)


def _text_block_after(document: str, marker: str) -> list[str]:
    marker_index = document.index(marker)
    fence_start = document.index("```text", marker_index)
    body_start = fence_start + len("```text")
    fence_end = document.index("```", body_start)
    block = document[body_start:fence_end]
    return [line.strip() for line in block.splitlines() if line.strip()]


def test_limited_organisation_docs_match_response_schema() -> None:
    document = DOC_PATH.read_text(encoding="utf-8")

    documented_fields = _text_block_after(
        document,
        "The limited organisation DTO may contain only:",
    )
    runtime_fields = list(PlatformLimitedOrganisationResponse.model_fields)

    assert documented_fields == runtime_fields


def test_platform_access_docs_preserve_limited_organisation_contract() -> None:
    document = DOC_PATH.read_text(encoding="utf-8")

    required_contracts = (
        "The limited organisation DTO must not return",
        "`suspended_at`",
        "`deleted_at`",
        "Limited list endpoints support these query parameters",
        "Ordering must be deterministic",
        "created_at desc",
        "id desc",
    )

    for expected_text in required_contracts:
        assert expected_text in document

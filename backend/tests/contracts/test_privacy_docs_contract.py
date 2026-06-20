from pathlib import Path

import pytest

from app.core.platform.permissions import PlatformPermission
from app.privacy.erasures.coverage import ERASURE_COVERAGE_MAP

pytestmark = [pytest.mark.contract, pytest.mark.privacy]

DOCS_ROOT = Path(__file__).parents[2] / "docs"
PRIVACY_DSR_DOC = DOCS_ROOT / "privacy-dsr.md"
CLOSURE_CHECKLIST_DOC = DOCS_ROOT / "privacy-dsr-328-closure-checklist.md"
CURRENT_STATE_DOC = DOCS_ROOT / "current-state.md"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_privacy_dsr_docs_include_current_platform_permissions() -> None:
    document = _read(PRIVACY_DSR_DOC)

    expected_permissions = (
        PlatformPermission.PRIVACY_REQUESTS_READ,
        PlatformPermission.PRIVACY_REQUESTS_REVIEW,
        PlatformPermission.PRIVACY_REQUESTS_EXECUTE_ERASURE,
        PlatformPermission.PRIVACY_EXPORT_ARTIFACTS_READ,
        PlatformPermission.GDPR_EXPORT,
        PlatformPermission.GDPR_ERASE,
    )

    for permission in expected_permissions:
        assert f"`{permission.value}`" in document


def test_privacy_dsr_docs_do_not_keep_stale_328_blockers() -> None:
    documents = (
        _read(PRIVACY_DSR_DOC),
        _read(CLOSURE_CHECKLIST_DOC),
        _read(CURRENT_STATE_DOC),
    )
    stale_claims = (
        "executable erasure coverage does not match the declared inventory",
        "executable erasure for memberships",
        "executable erasure or manual-review policy for organisations",
        "Final closure review has not been completed after the #407/#408",
    )

    for document in documents:
        for stale_claim in stale_claims:
            assert stale_claim not in document


def test_328_closure_checklist_lists_all_erasure_coverage_keys() -> None:
    document = _read(CLOSURE_CHECKLIST_DOC)

    for provider_key in ERASURE_COVERAGE_MAP:
        assert f"`{provider_key}`" in document


def test_328_closure_checklist_preserves_policy_based_rows() -> None:
    document = _read(CLOSURE_CHECKLIST_DOC)

    required_text = (
        "Membership, organisation and consent handling is intentionally ",
        "policy-based",
        "No current implementation or documentation blocker remains",
        "task ci",
    )

    for text in required_text:
        assert text in document

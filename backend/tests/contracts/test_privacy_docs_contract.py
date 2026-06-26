from pathlib import Path

import pytest

from app.core.platform.permissions import (
    ROLE_PERMISSIONS,
    PlatformPermission,
    PlatformRole,
)
from app.privacy.erasures.coverage import ERASURE_COVERAGE_MAP

pytestmark = [pytest.mark.contract, pytest.mark.privacy]

REPO_ROOT = Path(__file__).parents[3]
BACKEND_ROOT = Path(__file__).parents[2]
DOCS_ROOT = BACKEND_ROOT / "docs"

PRIVACY_DSR_DOC = DOCS_ROOT / "privacy-dsr.md"
CLOSURE_CHECKLIST_DOC = DOCS_ROOT / "privacy-dsr-328-closure-checklist.md"
CURRENT_STATE_DOC = DOCS_ROOT / "current-state.md"
RATE_LIMITING_DOC = DOCS_ROOT / "rate-limiting.md"
ADMIN_FRONTEND_DOC = DOCS_ROOT / "admin-frontend-client-generation.md"
PLATFORM_ACCESS_DOC = DOCS_ROOT / "access-control" / "en" / "platform-access.en.md"
SESSION_NOTES_DOC = REPO_ROOT / "SESSION_NOTES.md"

HISTORICAL_SLICE_DOCS = (
    DOCS_ROOT / "privacy-dsr-328-followup-review.md",
    DOCS_ROOT / "privacy-dsr-erasure-plan.md",
    DOCS_ROOT / "privacy-dsr-erasure-preview.md",
    DOCS_ROOT / "privacy-dsr-user-profile-erasure.md",
    DOCS_ROOT / "privacy-dsr-invite-erasure.md",
    DOCS_ROOT / "privacy-dsr-outbox-erasure.md",
    DOCS_ROOT / "privacy-dsr-erasure-orchestrator.md",
    DOCS_ROOT / "privacy-dsr-erasure-execution.md",
    DOCS_ROOT / "privacy-dsr-architecture-contract.md",
)

CURRENT_STATUS_DOCS = (
    PRIVACY_DSR_DOC,
    CLOSURE_CHECKLIST_DOC,
    CURRENT_STATE_DOC,
    RATE_LIMITING_DOC,
    ADMIN_FRONTEND_DOC,
    PLATFORM_ACCESS_DOC,
    SESSION_NOTES_DOC,
)

ALL_RECONCILED_DOCS = CURRENT_STATUS_DOCS + HISTORICAL_SLICE_DOCS


PLATFORM_PRIVACY_RATE_LIMIT_ROWS = (
    (
        "GET",
        "/api/v1/platform/privacy/data-subject-requests",
        "platform_read",
    ),
    (
        "GET",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}",
        "platform_read",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/review",
        "platform_write",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/approve",
        "platform_write",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/reject",
        "platform_write",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/cancel",
        "platform_write",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/execute-erasure",
        "platform_write",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/fulfil",
        "platform_write",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/data-subject-requests/{request_id}/export-artifact",
        "platform_write",
    ),
    (
        "GET",
        "/api/v1/platform/privacy/export-artifacts",
        "platform_read",
    ),
    (
        "GET",
        "/api/v1/platform/privacy/export-artifacts/{artifact_id}",
        "platform_read",
    ),
    (
        "POST",
        "/api/v1/platform/privacy/export-artifacts/{artifact_id}/download-url",
        "privacy_export_download_url",
    ),
)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _documented_role_permissions(document: str, role_name: str) -> set[str]:
    role_marker = f"{role_name}:"
    role_start = document.index(role_marker)
    role_end = document.index("```", role_start)
    role_block = document[role_start:role_end]
    permissions: set[str] = set()

    for line in role_block.splitlines()[1:]:
        stripped = line.strip()
        if not stripped.startswith("- "):
            continue
        permission = stripped.removeprefix("- ").strip()
        permission = permission.split(" ", maxsplit=1)[0]
        permissions.add(permission)

    return permissions


def _assert_rate_limit_matrix_row(
    document: str,
    *,
    method: str,
    endpoint: str,
    policy: str,
) -> None:
    expected_endpoint = f"`{endpoint}`"
    expected_policy = f"`{policy}`"
    matching_rows = [
        line for line in document.splitlines() if expected_endpoint in line
    ]

    assert matching_rows, f"missing rate-limit matrix row for {endpoint}"
    assert any(
        f"| {method} |" in row and expected_policy in row for row in matching_rows
    ), f"missing {method} {endpoint} policy {policy} in rate-limit matrix"


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


def test_platform_access_docs_match_compliance_officer_permissions() -> None:
    document = _read(PLATFORM_ACCESS_DOC)
    documented_permissions = _documented_role_permissions(
        document,
        "compliance_officer",
    )
    runtime_permissions = {
        permission.value
        for permission in ROLE_PERMISSIONS[PlatformRole.COMPLIANCE_OFFICER]
    }

    assert documented_permissions == runtime_permissions
    assert PlatformPermission.GDPR_ERASE.value not in documented_permissions
    assert PlatformPermission.PRIVACY_REQUESTS_EXECUTE_ERASURE.value in (
        documented_permissions
    )


def test_current_privacy_docs_do_not_keep_stale_328_blockers() -> None:
    stale_claims = (
        "executable erasure coverage does not match the declared inventory",
        "executable erasure for memberships",
        "executable erasure or manual-review policy for organisations",
        "Final closure review has not been completed after the #407/#408",
        "Issue #328 is not ready to close yet",
        "Issue #328 is still not ready for closure",
        "does not mutate data yet",
        "not wired into public API",
        "not exposed through public API",
        "does not fulfil the Data Subject Request",
        "public API/export/erasure remain follow-up scope",
        "API/export/erasure remain follow-up scope",
    )

    for path in ALL_RECONCILED_DOCS:
        document = _read(path)
        for stale_claim in stale_claims:
            assert stale_claim not in document, f"{path} contains {stale_claim!r}"


def test_historical_slice_docs_are_marked_as_superseded() -> None:
    required_text = (
        "Historical implementation-slice note",
        "It is not the current DSR/privacy source of truth",
        "backend/docs/privacy-dsr.md",
        "backend/docs/privacy-dsr-328-closure-checklist.md",
        "backend/docs/current-state.md",
    )

    for path in HISTORICAL_SLICE_DOCS:
        document = _read(path)
        for text in required_text:
            assert text in document, f"{path} does not mark stale scope clearly"


def test_privacy_docs_do_not_reference_unrelated_domain_examples() -> None:
    forbidden_terms = (
        "pati" + "ent",
        "clini" + "cal",
        "medi" + "cal tourism",
        "den" + "tal tourism",
    )

    for path in ALL_RECONCILED_DOCS:
        document = _read(path).lower()
        for term in forbidden_terms:
            assert term not in document, f"{path} contains unrelated term {term!r}"


def test_rate_limiting_docs_include_privacy_policies() -> None:
    document = _read(RATE_LIMITING_DOC)

    required_text = (
        "`privacy_dsr_submit`",
        "`privacy_export_download_url`",
        "/api/v1/privacy/data-subject-requests",
        "/api/v1/privacy/export-artifacts/{artifact_id}/download-url",
        "/api/v1/platform/privacy/export-artifacts/{artifact_id}/download-url",
        "DSR submit/cancel endpoints are rate limited",
        "export artifact download URL generation is rate limited",
    )

    for text in required_text:
        assert text in document


def test_rate_limiting_docs_include_all_platform_privacy_endpoints() -> None:
    document = _read(RATE_LIMITING_DOC)

    for method, endpoint, policy in PLATFORM_PRIVACY_RATE_LIMIT_ROWS:
        _assert_rate_limit_matrix_row(
            document,
            method=method,
            endpoint=endpoint,
            policy=policy,
        )

    assert "Platform privacy rate-limit model" in document
    assert "platform privacy read/write route-limit documentation coverage" in document


def test_platform_docs_include_platform_privacy_tag() -> None:
    documents = (
        _read(ADMIN_FRONTEND_DOC),
        _read(PLATFORM_ACCESS_DOC),
    )

    for document in documents:
        assert "platform-privacy" in document
        assert "generic `platform` tag" in document


def test_admin_frontend_doc_uses_backend_relative_uv_commands() -> None:
    document = _read(ADMIN_FRONTEND_DOC)

    assert "uv run pytest -q tests/contracts/test_openapi_platform_contract.py" in (
        document
    )
    stale_command = (
        "pytest -q backend/tests/contracts/test_openapi_platform_contract.py"
    )
    assert stale_command not in document


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

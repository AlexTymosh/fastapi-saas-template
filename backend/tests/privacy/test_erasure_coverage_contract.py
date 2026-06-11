from __future__ import annotations

import pytest

from app.privacy.erasures.coverage import (
    ERASURE_COVERAGE_MAP,
    ErasureCoverageDecision,
    executable_erasure_provider_keys,
    inventory_erasure_provider_keys,
)
from app.privacy.erasures.orchestrator import erasure_orchestration_provider_order
from app.privacy.erasures.plan import build_erasure_provider_plan

pytestmark = [pytest.mark.privacy, pytest.mark.contract]


def test_erasure_coverage_map_accounts_for_every_inventory_provider() -> None:
    assert set(ERASURE_COVERAGE_MAP) == set(inventory_erasure_provider_keys())


def test_erasure_coverage_map_matches_plan_tables() -> None:
    by_key = {entry.provider_key: entry for entry in build_erasure_provider_plan()}

    for provider_key, coverage_entry in ERASURE_COVERAGE_MAP.items():
        assert coverage_entry.table_name == by_key[provider_key].table_name
        assert coverage_entry.rationale


def test_executable_coverage_is_wired_into_orchestrator_order() -> None:
    executable_keys = executable_erasure_provider_keys()
    provider_order = erasure_orchestration_provider_order()

    assert executable_keys <= set(provider_order)
    assert len(provider_order) == len(set(provider_order))


def test_all_remaining_inventory_targets_have_runtime_or_policy_decision() -> None:
    decisions = {entry.decision for entry in ERASURE_COVERAGE_MAP.values()}

    assert ErasureCoverageDecision.EXECUTABLE in decisions
    assert ErasureCoverageDecision.RETAIN_BY_POLICY in decisions
    assert ErasureCoverageDecision.MANUAL_REVIEW_POLICY in decisions
    assert all(
        entry.decision
        in {
            ErasureCoverageDecision.EXECUTABLE,
            ErasureCoverageDecision.RETAIN_BY_POLICY,
            ErasureCoverageDecision.MANUAL_REVIEW_POLICY,
        }
        for entry in ERASURE_COVERAGE_MAP.values()
    )

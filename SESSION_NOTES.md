# SESSION_NOTES — DSR outbox export email normalisation

Date: 2026-07-17
Repository: `AlexTymosh/fastapi-saas-template`
Target base branch: `main`
Suggested branch: `fix/privacy-outbox-export-email-normalization`
Parent scope: issue `#328`

## Current task

Fix the P2 gap where `OutboxSubjectReferencesExportProvider` matched
`outbox_events.payload_json["email"]` with an exact comparison instead of the
same trim/lower normalisation used by invite and erasure lookup paths.

## Decision

This is small enough for one PR.

Keep it separate from the other P2 findings because it has a narrow risk area:
subject export completeness for legacy or dirty outbox payload email values.
Do not combine it with export artifact lifecycle/status coverage or retention
storage-cleanup ordering.

## Change summary

- In `backend/app/privacy/exporters/subject_data.py`, normalise the outbox JSON
  payload email predicate with:
  `func.lower(func.trim(OutboxEvent.payload_json["email"].as_string()))`.
- Keep the existing aggregate-id invite subquery path unchanged.
- Add a regression test proving outbox payload-only matches work when the JSON
  email has leading/trailing whitespace and mixed case.
- Update export-provider documentation to state that outbox JSON email payload
  predicates must follow the same trim/lower rule.

## Files touched

- `backend/app/privacy/exporters/subject_data.py`
- `backend/tests/privacy/test_subject_data_exporter_email_normalization.py`
- `backend/docs/privacy-dsr-export-providers.md`
- `SESSION_NOTES.md`

## Boundaries

- No new dependency.
- No schema or migration change.
- No payload shape change.
- No change to redaction rules.
- No change to erasure provider logic; this aligns export behaviour with the
  existing erasure predicate.
- No direct export of outbox `payload_json.email` or `encrypted_raw_token`; they
  remain redacted fields.

## Static impact check

Affected runtime area:

- `CrossTableSubjectDataExporter`
- `iter_subject_export_json_chunks()` indirectly, because it uses the same
  provider registry from `subject_data.py`
- export archive generation, because it streams records from these providers

Expected impact:

- Legacy outbox events where only `payload_json.email` links the row to the
  subject now appear in the subject export.
- The comparison stays backend-agnostic through SQLAlchemy JSON `.as_string()`
  and SQL `lower(trim(...))`.
- Existing invite aggregate-id lookup remains unchanged.

Risk review:

- Performance risk is low. This predicate is used only during DSR export, not
  hot request-path reads.
- Index usage on JSON email is not guaranteed, but this was already a JSON
  predicate path. Creating a functional JSON index is not justified for this
  template-level edge case unless real production volume proves it necessary.
- PostgreSQL rendering must still be covered by the existing container-level
  provider tests for JSON predicates.


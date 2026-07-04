# Authorised representative DSR fulfilment semantics

> **Historical implementation-slice note**
>
> This document records the PR-328-9C implementation slice.
> It is not the current DSR/privacy source of truth. Use
> `backend/docs/privacy-dsr.md`,
> `backend/docs/privacy-dsr-328-closure-checklist.md`, and
> `backend/docs/current-state.md` for the current project state and closure
> contract.

## Scope

This document records the fulfilment semantics for DSRs submitted by an
authorised representative after representative intake and platform authority
review are complete.

This is a backend workflow contract. It does not add a frontend or a document
upload/evidence-storage system.

## State model

A representative DSR keeps two distinct identities:

- `requester_user_id`: the authenticated representative who submitted the DSR;
- `subject_user_id`: the represented data subject whose personal data is in
  scope.

A representative DSR may only move to ordinary approval after platform review
sets `representative_status=verified`. Rejected or pending representative
authority remains blocked by the central approval guard.

## Export semantics

For a verified representative export DSR:

- the generated export archive is built for `subject_user_id`;
- the export artifact remains owned by `requester_user_id`, because the verified
  representative is the intended delivery recipient;
- self-service export-artifact reads/downloads remain requester-scoped;
- the represented subject cannot use requester-scoped export-artifact endpoints
  to download a representative-owned artifact;
- DSR workflow records in the subject export minimise unrelated requester,
  reviewer and verifier identifiers.

Platform staff may create the export artifact after approval, but that does not
make the staff user the artifact owner. The owner remains the DSR requester.

## Erasure semantics

For a verified representative erase DSR:

- platform staff still executes the erasure through the dedicated erasure
  execution boundary;
- the representative requester cannot bypass platform execution rules;
- the erasure target is `subject_user_id`, not `requester_user_id`;
- self-erasure rejection remains tied to the platform executor and the represented
  subject, not to the representative requester;
- successful erasure may minimise DSR workflow links according to the privacy
  inventory, but it must not erase the representative merely because they
  submitted the DSR.

## Regression coverage

`tests/privacy/test_dsr_representative_fulfilment.py` covers:

- verified representative export artifacts use subject data;
- representative export artifacts are requester-owned;
- the represented subject cannot read a requester-owned artifact via own-artifact
  endpoints;
- representative erasure executes against the represented subject and leaves the
  representative account intact.

## Out of scope

- Frontend screens for representative workflows.
- Uploading or storing documentary authority evidence.
- External identity proofing integrations.
- Non-local represented subjects that do not have a local user projection.

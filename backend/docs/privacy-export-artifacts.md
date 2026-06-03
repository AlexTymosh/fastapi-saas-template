# Privacy Export Artifacts

## Scope

Export artifacts are generated asynchronously from approved export DSRs.

## Current behaviour

- Export generation is queued, then processed by a worker-friendly command.
- Local storage backend is for development and test only.
- `s3_compatible` is the required staging/production backend when privacy exports are enabled.
- Download URLs are short-lived and signed for local development semantics.
- S3-compatible downloads use short-lived SigV4 presigned GET URLs.
- Raw export payloads are not stored in the database.
- Audit metadata is intentionally minimised and does not include payload/storage paths/tokens.
- `--dry-run` worker mode performs one non-mutating count pass and then exits predictably.

## Out of scope

- Full personal-data coverage across all product tables.
- Erasure/anonymisation execution.
- Retention runners.
- Authorised representative workflows.
- Frontend/UI.

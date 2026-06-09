# Privacy Export Artifacts

## Scope

Export artifacts are generated asynchronously from approved export DSRs.

## Current behaviour

- Export generation is queued, then processed by a worker-friendly command.
- Local storage backend is for development and test only.
- `s3_compatible` is the required staging/production backend when privacy
  exports are enabled.
- Download URLs are short-lived and signed for local development semantics.
- S3-compatible downloads use short-lived SigV4 presigned GET URLs.
- Raw export payloads are not stored in the database.
- Export payloads are assembled from the current cross-table subject export
  providers.
- Audit metadata is intentionally minimised and does not include payload/storage
  paths/tokens.
- `--dry-run` worker mode performs one non-mutating count pass and then exits
  predictably.
- Expired ready artifacts are processed by the privacy retention runner, which
  deletes the stored archive object, clears storage metadata, marks the artifact
  as `expired`, and synchronises the linked DSR execution state.

## Maintenance runner

Run the privacy export retention runner with:

```text
python -m app.privacy.retention_cli
```

The runner:

- finds ready export artifacts whose `expires_at` is in the past;
- deletes the stored local/S3-compatible archive object;
- clears `storage_key`, filename, content type, size, and checksum metadata;
- marks the artifact as `expired`;
- records an `export_artifact_expired` audit event;
- synchronises the linked export DSR execution state.

Use `--dry-run` to preview the number of artifacts that would be processed
without mutating the database or deleting storage objects.

## Out of scope

- Streaming archive generation for very large exports.
- Authorised representative workflows.
- Frontend/UI.

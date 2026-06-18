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
  providers. This is export coverage only and does not imply complete
  executable erasure coverage for the same tables.
- Audit metadata is intentionally minimised and does not include payload/storage
  paths/tokens.
- `--dry-run` worker mode performs one non-mutating count pass and then exits
  predictably.
- Expired ready artifacts are processed by the privacy retention runner, which
  deletes the stored archive object, clears storage metadata, marks the artifact
  as `expired`, and synchronises the linked DSR execution state.

## Export artifact cardinality

DSR export requests use a multi-artifact history model.

One `DataSubjectRequest` may have multiple `ExportArtifact` rows linked by
`export_artifacts.data_subject_request_id`. This supports repeated export
generation attempts, regenerated archives, and historical artifact records.

The current export execution state for a DSR is derived from the newest export
artifact for that request. Older artifacts may remain downloadable until they
expire, but they must not overwrite the DSR execution state after a newer
artifact has been queued or processed.

`data_subject_requests.export_artifact_id` is a legacy reserved pointer. It is
not the runtime source of truth for export artifact ownership or execution
state.

If the product later requires a single-active-artifact model, that should be a
separate contract change with either existing-active-artifact reuse or a
database constraint for active statuses.

## Worker operations

The export artifact worker can run as a one-shot local command, a non-mutating
dry run, or a long-running Compose service.

One-shot local drain pass from the repository root:

```text
task privacy:export-worker:once
```

Non-mutating local smoke check from the repository root:

```text
task privacy:export-worker:dry-run
```

Direct backend command equivalents:

```text
python -m app.commands.privacy_export_worker --once
python -m app.commands.privacy_export_worker --dry-run --once
```

The command supports `--batch-size` and `--poll-interval`. With the default
`--poll-interval 0`, the worker drains available work and exits once no queued
artifacts remain. With a positive poll interval, the worker waits and polls
again after an empty iteration, which is the mode used by the Compose service.

Local Compose service:

```text
docker compose --profile privacy-exports up -d privacy-export-worker
```

The `privacy-export-worker` service is profile-gated, so it is not part of the
default local stack. It depends on PostgreSQL and Redis and uses the same backend
image and environment model as the API and outbox workers.

Optional Compose environment knobs:

```text
PRIVACY_EXPORT_WORKER_BATCH_SIZE=10
PRIVACY_EXPORT_WORKER_POLL_INTERVAL_SECONDS=5
```

For staging or production, run this as a separate worker process using the same
application image and the real deployment environment. Run migrations as a
separate release step before starting the worker. Do not rely on the local
Compose profile as a production deployment manifest.

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

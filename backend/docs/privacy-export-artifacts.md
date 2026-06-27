# Privacy Export Artifacts

## Scope

Export artifacts are generated asynchronously from approved export DSRs.

## Current behaviour

- Export generation is queued, then processed by a worker-friendly command.
- Local storage backend is for development and test only.
- `s3_compatible` is the required staging/production backend when privacy
  exports are enabled.
- Local download URLs use signed `local://privacy-export/...` references for
  development and tests only. They are not HTTP URLs and must not be exposed as
  a browser-download contract in staging or production.
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

## Local download URL contract

The local storage backend signs opaque `local://privacy-export/...` references.
These values are local adapter references, not HTTP URLs.

The local backend exists for development and tests only. It is intentionally not
a production delivery mechanism and must not be treated as a public browser
URL. Production-like environments must use the `s3_compatible` backend so the
storage provider issues short-lived SigV4 presigned HTTP GET URLs.

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


## Delivery evidence

Download URL creation records that a URL was issued. It does not prove
that the artifact was received, especially for S3-compatible presigned
URLs. Confirmed delivery is recorded through the explicit delivery
confirmation endpoints. Those endpoints reuse the export download URL
rate-limit policy and authorised artifact-scoped bucket before they
update `downloaded_at`, increment `download_count`, and sync the export
DSR execution state.

## Migration notes for URL issuance split

Before delivery confirmation existed, `downloaded_at` and `download_count`
represented URL issuance, not confirmed receipt. The migration moves those
legacy values into `download_url_issued_at` and `download_url_issue_count`, then
clears the confirmed-delivery fields so historical rows are not treated as
confirmed delivery evidence.

Delivery confirmation is idempotent. Repeated or concurrent confirmations must
leave `download_count` at `1` and must not create duplicate delivery evidence.

Legacy DSR execution state is reclassified from the latest export artifact after
that backfill. Latest ready artifacts become `ready`; latest expired artifacts
become failed with `artifact_expired`, because URL issuance alone is not
confirmed delivery evidence.

### Delivery confirmation availability guard

Delivery confirmation uses an atomic conditional update that only succeeds while
the artifact is still ready, non-expired, has storage metadata, has not already
been confirmed, and its linked DSR is still an eligible export request. Eligible
DSRs are `approved` or `fulfilled` export requests with requester and subject
links still present. If retention, subject-erasure cancellation, or platform DSR
cancellation wins the race before the confirmation update, the request is
rejected instead of writing confirmed delivery evidence onto an unavailable or
ineligible artifact.

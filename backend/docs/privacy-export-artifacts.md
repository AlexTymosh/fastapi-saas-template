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
- Export artifact ZIP generation writes `export.json` incrementally into a
  temporary archive file and uploads the prepared file to the selected storage
  backend. It must not materialise the full JSON payload string or ZIP archive
  bytes in memory before storage.
- Before storage upload, the worker commits a stable `storage_key` upload intent
  on the still-active processing lease. Retries reuse that key instead of
  creating an untracked object.
- Storage publication is immutable. Local storage atomically publishes a
  completed staged file without replacing an existing key. S3-compatible
  storage uses a conditional `PutObject` with `If-None-Match: *` and a
  server-validated SHA-256 checksum.
- Audit metadata is intentionally minimised and does not include payload/storage
  paths/tokens.
- `--dry-run` worker mode performs one non-mutating count pass and then exits
  predictably.
- Expired ready artifacts are processed by the privacy retention runner, which
  deletes the stored archive object, clears storage metadata, marks the artifact
  as `expired`, and synchronises the linked DSR execution state.

## Export archive generation

Export archives use the `json_zip` format and contain a single `export.json`
member. The generator streams JSON chunks from the subject export providers into
`ZipFile.open("export.json", mode="w")`, then uploads the completed temporary ZIP
file with the selected storage adapter.

The generated archive metadata is derived from the completed temporary file:

- `size_bytes` is the archive file size;
- `checksum_sha256` is calculated by reading the file in bounded chunks;
- `max_artifact_size_bytes` is checked after the ZIP has been closed and before
  the file is uploaded to storage;
- temporary files are removed after upload, and also after generation failures.

Archive preparation, upload and the `ready` transition use separate transaction
phases. The preparation phase records or reuses the upload intent. The worker
commits it, revalidates the processing token, lease, backend and key, and only
then calls immutable storage publication outside the database transaction. The
final transaction stores file metadata, marks the artifact `ready`, synchronises
the DSR execution state and records the audit event.

The storage precondition remains effective for the entire external write. If a
lease turns over after validation, a stale worker cannot replace or interleave
with the object published by the current worker. An existing object is accepted
only when its SHA-256 checksum and size match the prepared archive. Different
bytes at the committed key fail closed; the current lease records a failed,
non-downloadable artifact and the normal cleanup workflow removes the object.

If upload or final persistence fails, the worker first commits the artifact as
non-downloadable `failed` while retaining `storage_key`. It then attempts object
deletion outside a database transaction and clears storage metadata in a later
transaction only after deletion succeeds. A failed or interrupted cleanup keeps
the key for the retention runner. Deleting a missing object is treated as an
idempotent success.

A stale processing lease keeps its recorded upload intent. Recovery requeues the
artifact and the next lease reuses the same key. An old lease must fail the
pre-upload validation and cannot transition the row to `ready`. If turnover
occurs during storage I/O, immutable publication prevents the old lease from
overwriting bytes selected by the newer lease.

Deployment environments must provide writable temporary storage for export
workers. For large exports, size the writable path for at least the configured
`PRIVACY_EXPORTS__MAX_ARTIFACT_SIZE_BYTES` plus normal filesystem overhead.

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

## S3 versioning and permanent deletion

The S3-compatible adapter performs key-level `DeleteObject` cleanup. In a
versioning-enabled bucket, a key-level delete can create a delete marker while
retaining older object versions. Before enabling privacy exports, operators must
therefore use a dedicated unversioned bucket/prefix or configure and verify a
lifecycle policy that permanently expires noncurrent versions and removes
expired delete markers within the required retention SLA. Object Lock or
replication policy must not extend personal-export retention unintentionally.

The S3-compatible provider must also implement standard conditional
`PutObject` requests with `If-None-Match: *`, SHA-256 checksum validation and
read-after-write `HeadObject` metadata. Deployment smoke tests must fail closed
instead of falling back to an unconditional overwrite when these capabilities
are unavailable.

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

The privacy export retention runner performs one bounded cleanup pass and then
exits. It is safe for local manual use, scheduled jobs, and external schedulers
that run the command as a single instance.

First run a non-mutating smoke check from the repository root:

```text
task privacy:retention:dry-run
```

Then run one cleanup pass from the repository root:

```text
task privacy:retention:once
```

Direct backend command equivalents:

```text
python -m app.privacy.retention_cli --dry-run
python -m app.privacy.retention_cli
python -m app.privacy.retention_cli --batch-size 500
```

The runner:

- finds ready export artifacts whose `expires_at` is in the past;
- retries storage-object purges for cancelled export artifacts created before a
  subject erasure request;
- retries storage-object purges for failed generation or upload attempts that
  still retain an upload-intent key;
- deletes the stored local/S3-compatible archive object;
- clears `storage_key`, filename, content type, size, and checksum metadata;
- marks expired ready artifacts as `expired`;
- records an `export_artifact_expired` audit event for expired ready artifacts;
- synchronises the linked export DSR execution state.

Use `--dry-run` to preview the number of artifacts that would be processed
without mutating the database or deleting storage objects. Use `--batch-size` to
bound a scheduled pass.

Cleanup priority within the export-artifact batch is subject-erasure retries,
failed generation/upload retries, READY-to-EXPIRED transitions, and previously
expired object retries. A storage failure does not prevent unrelated READY rows
from becoming non-downloadable when useful work remains in the pass.

### Production scheduling guidance

Run retention after database migrations and with the same application image,
settings, database, storage backend, and secret sources as the API. Do not run it
from a developer workstation against staging or production storage.

Use exactly one active retention runner per environment unless a later change
adds an explicit distributed lock or row-claiming contract for retention. The
current runner is intended as a one-shot maintenance command, not a continuously
polling worker.

Supported scheduling patterns:

- **Manual one-shot:** run `task privacy:retention:dry-run`, inspect logs, then
  run `task privacy:retention:once`.
- **systemd timer:** create a oneshot service that runs
  `python -m app.privacy.retention_cli` from the deployed backend environment,
  then trigger it from a timer. Keep the service non-overlapping.
- **Kubernetes CronJob:** run the backend image with command
  `python -m app.privacy.retention_cli`, set `concurrencyPolicy: Forbid`, and
  set a bounded `successfulJobsHistoryLimit` / `failedJobsHistoryLimit`.
- **External scheduler:** call the same one-shot command in the deployment
  platform, ensuring only one run can be active at a time.

Example Kubernetes CronJob command shape:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: privacy-export-retention
spec:
  schedule: "17 3 * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: retention
              image: your-backend-image
              command:
                - python
                - -m
                - app.privacy.retention_cli
```

## Out of scope

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

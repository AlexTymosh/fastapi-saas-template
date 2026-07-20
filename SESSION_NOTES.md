# SESSION_NOTES — Export artifact retention purge ordering

## Current task

Close the P2 retention gap: export artifact retention must not delete a stored
archive object while rollback can still restore the database row to `ready`.

## Scope boundaries

- Keep this PR limited to export artifact retention ordering.
- Do not mix this with export schema, UI, representative evidence or deployment
  manifest follow-ups.
- Do not add a dependency or a new table for this fix.
- Preserve caller-owned transactions; retention helpers must not commit.
- Read `docs/privacy-dsr-retention.md` before changing retention behavior.
- Keep code lines at or below 88 characters.

## Required #328 contract anchors

These anchors remain here only because the current docs contract still reads
`SESSION_NOTES.md`.

- `PR #441 is merged into main.`
- `10F | Final #328 closure reconciliation | Yes | Done`
- `PR-328-10F is done in this patch`
- `Status: Ready after this PR and a green task ci run.`
- Keep `versioned export payload schema contract` tracked in canonical docs.

## Implemented approach

- READY artifacts are first marked `expired` in the database.
- `storage_key` remains as a retry marker after the READY -> EXPIRED transition.
- Stored objects are purged only from rows already in a non-downloadable state:
  `expired`, or subject-erasure `cancelled`.
- Rollback after the expiry transition restores a valid READY row with an
  existing storage object.
- A later retention pass deletes the stored object and clears storage metadata.


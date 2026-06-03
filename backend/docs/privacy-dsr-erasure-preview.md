# DSR erasure preview

This slice adds a dry-run preview layer for `erase` Data Subject Requests.

The preview is intentionally non-destructive. It does not update, delete or
anonymise database rows. It translates the inventory-derived erasure provider
plan into a request-scoped execution preview so later destructive providers can
be implemented behind a safer contract.

## Why this exists

Erasure is the riskiest part of issue #328 because it can permanently remove or
minimise personal data while audit and tenant integrity still need to be
preserved.

The project should not jump directly from inventory metadata to SQL mutations.
The safer sequence is:

1. Inventory-derived erasure provider plan.
2. Request-scoped erasure preview.
3. User, invite and outbox erasure providers.
4. Audit minimisation providers.
5. Retention and purge runners.
6. Platform API execution controls.

## Current behaviour

`build_erasure_preview()` accepts a DSR id, subject user id and request type. It
rejects non-`erase` request types and returns:

- all planned erasure providers;
- execution mode for each provider;
- retention policy key;
- manual-review requirement;
- automatic/manual/retain-only/not-applicable provider groups.

Retain-with-legal-basis providers are grouped as `retain_only` before the
manual-review fallback is applied. They may still carry
`requires_manual_review=true`, but they are not mixed into the generic
`manual_review_required` provider group.

The preview deliberately does not query the database yet. Database-row counting
and operator-facing diff previews should be added in the next implementation
slice together with the first concrete erasure providers.

## Remaining work

The next branch should add controlled erasure providers for:

- `users.anonymise_profile`;
- `invites.anonymise_or_purge_subject_references`;
- `outbox.purge_or_scrub_payload`.

That branch should keep audit minimisation and retention purge out of scope.

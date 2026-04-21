# Keycloak identity contract (backend projection)

This backend treats Keycloak as the identity source of truth and stores a local application projection.

## Contract

- `users.external_auth_id` (mapped from JWT `sub`) is the **only stable identity key** in the local database.
- The backend must **never identify a user by email**.
- `users.email` is mutable profile data projected from Keycloak claims.
- `users.email_verified` is mutable profile data projected from Keycloak claims.
- If claims change for the same `sub`, the backend updates the existing local `users` row instead of creating a new row.
- JIT provisioning runs on authenticated requests through `provision_current_user(...)`.
- The local `users` record is an application projection and not the identity source of truth.

## Practical implications

- `external_auth_id` remains unique.
- `email` is not a DB identity constraint.
- Claim refresh is idempotent: unchanged claims do not trigger writes.

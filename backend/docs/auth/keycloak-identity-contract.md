# Keycloak identity contract (local user projection)

This backend treats Keycloak as the identity source of truth and keeps a local user projection for application use.

## Contract

- `users.external_auth_id` (mapped from JWT `sub`) is the **only stable identity key** in the local database.
- The backend **must never identify users by email**.
- `users.email` is mutable profile data projected from Keycloak claims.
- `users.email_verified` is mutable profile data projected from Keycloak claims.
- If claims change for the same `sub`, the backend updates the existing local row instead of creating a new user.
- JIT provisioning happens on authenticated requests (for example `/api/v1/users/me` and organisation/member endpoints).
- The local `users` table is an application projection for authorization and domain linkage; it is not the identity authority.

## Operational implications

- `external_auth_id` remains unique and required.
- `email` is not used as a uniqueness boundary for identity lifecycle decisions.
- Claim synchronization is update-in-place for an existing `external_auth_id`.

# Keycloak identity contract (local user projection)

This backend treats Keycloak as the identity source of truth and keeps a local user projection for application use.

## Contract rules

1. **Identity linkage key**
   - `users.external_auth_id` (JWT `sub`) is the only stable identity key.
   - `sub` is required for authenticated human-user requests.
   - If `sub` is missing or invalid, the backend must fail identity mapping/authentication; it must not invent fallback identifiers.

2. **Claims and projection**
   - `email`, `email_verified`, `first_name`, and `last_name` are projected profile claims and may be absent depending on Keycloak token/profile configuration.
   - Missing optional claims do not break identity linkage; projection still proceeds using `external_auth_id`.
   - `email` may be null/absent and is never used as the identity key.

3. **Refresh behavior**
   - The same `sub` must always update the same local `users` row.
   - Claim changes (for example `email` or `email_verified`) update the existing row in place.
   - Unchanged claims should not trigger unnecessary writes.
   - A changed `email` must not create a new user.

4. **Provisioning before authorization**
   - JIT user projection runs on authenticated request paths (for example `/api/v1/users/me`, organisation, and membership endpoints).
   - Local projection creation/refresh occurs before organisation-specific authorization checks.
   - A `403` authorization result does not imply provisioning failed.

5. **Authorization/domain linkage model**
   - The local `users` table is an application projection used for authorization and domain relations.
   - Onboarding and organisation membership linkage attach to local user rows, not directly to transient JWT claims.

6. **Database invariants**
   - `users.external_auth_id` is required and unique.
   - `users.email` is mutable profile data and is not a uniqueness boundary for identity lifecycle decisions.

7. **Token scope**
   - This contract currently targets interactive human-user tokens.
   - Service/machine tokens are not part of this contract unless explicitly supported by a separate specification.

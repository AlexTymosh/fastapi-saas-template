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

## Operational rules

1. **Claim requirements**
   - `sub` is required. Requests without a valid non-empty `sub` cannot be mapped to a local user.
   - `email`, `email_verified`, `first_name`, and `last_name` are optional projection claims; missing optional claims must not block identity linkage.

2. **Missing or null email**
   - Identity linkage must still succeed when `email` is missing or `null`.
   - The local projection must still be created/refreshed using `external_auth_id=sub`.

3. **Claim refresh semantics**
   - The same `sub` must always resolve to the same local `users` row.
   - Changes to `email`/profile claims update that same row in place and must not create a second user.
   - When projected claims are unchanged, no unnecessary write should be performed.
   - `/api/v1/users/me` must not refresh profile claims for an existing suspended local user. It must fail authorization before mutating local projection fields.

4. **Identity before authorization**
   - Local user projection is created/refreshed before organisation-scoped authorization checks.
   - A `403` authorization result does not imply projection failure; the authenticated principal may still be newly provisioned locally.

5. **Token audience expectations**
   - This contract targets Keycloak access tokens for this API that represent an end user identity (`sub`).
   - API callers must send access tokens, not ID tokens.
   - Access tokens must contain the backend API/resource-server audience configured in `AUTH__AUDIENCE`.
   - When `AUTH__ALLOWED_AUTHORIZED_PARTIES` is configured, the access-token `azp` claim must identify an allowed frontend/admin OAuth client.
   - Service-account/machine-token identity semantics are out of scope unless explicitly documented by a separate contract.

6. **Database invariants**
   - `users.external_auth_id` is required and unique.
   - `users.email` is mutable profile data and not a uniqueness boundary.
   - Domain links (for example memberships/onboarding state) attach to the local user projection, not directly to JWT claim values.
   - A local user may have **at most one active** organisation membership at a time. Membership is the only organisation link for the user projection.
   - Moving a user to another organisation must be modeled as transfer/reassignment (ending previous active membership before activating the next), not simultaneous multi-organisation membership.

7. **Failure behavior**
   - If `sub` is missing/invalid, authentication or identity mapping must fail.
   - The backend must not invent fallback identifiers (for example deriving identity from email).


## Local development notes (backend-only)

- Keycloak is used only as identity provider (JWT issuer + claims source).
- This backend validates bearer tokens and projects users locally by `external_auth_id == sub`.
- Runtime JWT settings source of truth is `AUTH__*` (`AUTH__ENABLED`, `AUTH__ISSUER_URL`, `AUTH__AUDIENCE`, `AUTH__ALLOWED_AUTHORIZED_PARTIES`).
- `AUTH__CLIENT_ID` is retained only as backwards-compatible context for optional `resource_access` projection; it is not the production validation control.
- Audience validation uses `AUTH__AUDIENCE`; local default is `fastapi-api`.
- Authorised-party validation uses `AUTH__ALLOWED_AUTHORIZED_PARTIES` against the access-token `azp` claim when configured.
- Staging/prod require fail-fast OIDC metadata validation with `AUTH__METADATA_VALIDATION=fail`.
- Local realm bootstrap intentionally separates browser login client (`fastapi-web`) from API/resource audience client (`fastapi-api`).
- JWT signature verification is intentionally limited to `RS256`.
- Organisations, memberships, onboarding, and invites stay in the local business database.
- Registration, email verification, and CAPTCHA are intentionally delegated to Keycloak (not implemented in this backend).

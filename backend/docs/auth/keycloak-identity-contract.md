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

4. **Identity before authorization**
   - Local user projection is created/refreshed before organisation-scoped authorization checks.
   - A `403` authorization result does not imply projection failure; the authenticated principal may still be newly provisioned locally.

5. **Token audience expectations**
   - This contract currently targets human user access tokens that represent an end user identity (`sub`).
   - Service-account/machine-token identity semantics are out of scope unless explicitly documented by a separate contract.

6. **Database invariants**
   - `users.external_auth_id` is required and unique.
   - `users.email` is mutable profile data and not a uniqueness boundary.
   - Domain links (for example memberships/onboarding state) attach to the local user projection, not directly to JWT claim values.
   - A local user may have **at most one** membership row. Membership is the only organisation link for the user projection.
   - Creating a second membership for the same user is forbidden by project policy and backed by a database uniqueness constraint on `memberships.user_id`.

7. **Failure behavior**
   - If `sub` is missing/invalid, authentication or identity mapping must fail.
   - The backend must not invent fallback identifiers (for example deriving identity from email).


## Local development notes (backend-only)

- Keycloak is used only as identity provider (JWT issuer + claims source).
- This backend validates bearer tokens and projects users locally by `external_auth_id == sub`.
- Runtime JWT settings source of truth is `AUTH__*` (`AUTH__ENABLED`, `AUTH__ISSUER_URL`, `AUTH__AUDIENCE`, `AUTH__CLIENT_ID`).
- Role extraction for `resource_access` uses `AUTH__CLIENT_ID` (auth-scoped config).
- Local dev intentionally uses two distinct Keycloak clients:
  - `fastapi-web`: browser/public Authorization Code + PKCE login client.
  - `fastapi-api`: API/resource audience descriptor client for backend `aud` validation.
- Runtime split remains: `AUTH__CLIENT_ID=fastapi-web` for `resource_access.fastapi-web.roles`, and `AUTH__AUDIENCE=fastapi-api` for JWT audience validation.
- JWT signature verification is intentionally limited to `RS256`.
- Organisations, memberships, onboarding, and invites stay in the local business database.
- Registration, email verification, and CAPTCHA are intentionally delegated to Keycloak (not implemented in this backend).

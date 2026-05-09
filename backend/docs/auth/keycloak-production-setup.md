# Keycloak production setup for backend JWT validation

This backend acts as an **OAuth2 Resource Server**. Keycloak authenticates users and issues tokens; the FastAPI backend validates incoming bearer access tokens for this API and then resolves tenant/platform authorization from its own database.

## Token contract

API clients must call the backend with a Keycloak **access token**, not an ID token. Accepted tokens must satisfy all configured runtime checks:

- `alg` is `RS256`.
- `kid` is present when `AUTH__REQUIRE_KID=true`.
- Signature validates against cached Keycloak JWKS.
- `iss` exactly matches `AUTH__ISSUER_URL` after local settings normalisation.
- `aud` contains `AUTH__AUDIENCE`.
- `exp`, `iss`, `sub`, and the configured audience are present.
- `iat` is present when `AUTH__REQUIRE_IAT=true`.
- `azp` is listed in `AUTH__ALLOWED_AUTHORIZED_PARTIES` when that list is configured.
- `exp - iat` does not exceed `AUTH__MAX_TOKEN_LIFETIME_SECONDS`.

Authorization is DB-driven. The backend does not use Keycloak realm/client roles, direct `roles`, `realm_access`, `resource_access`, or similar IdP role claims as request-time tenant or platform permissions. Tenant access comes from local memberships, and platform access comes from `platform_staff`. External IdP roles may only be considered in the future as input for controlled, idempotent, audited JIT provisioning that writes local `memberships` or `platform_staff` records before any permission is granted.

## Required staging/prod settings

Staging and production fail startup unless the following auth settings are complete:

```env
AUTH__ENABLED=true
AUTH__ISSUER_URL=https://keycloak.example.com/realms/<realm>
AUTH__AUDIENCE=fastapi-api
AUTH__ALLOWED_AUTHORIZED_PARTIES=fastapi-web,fastapi-admin
AUTH__METADATA_VALIDATION=fail
```

Production also rejects non-HTTPS `AUTH__ISSUER_URL` and explicitly configured non-HTTPS `AUTH__JWKS_URL`.

Recommended defaults:

```env
AUTH__ALGORITHMS=RS256
AUTH__LEEWAY_SECONDS=30
AUTH__REQUIRE_KID=true
AUTH__REQUIRE_IAT=true
AUTH__MAX_TOKEN_LIFETIME_SECONDS=3600
AUTH__DISCOVERY_CACHE_TTL_SECONDS=300
AUTH__JWKS_CACHE_TTL_SECONDS=300
AUTH__JWKS_REFRESH_COOLDOWN_SECONDS=30.0
AUTH__JWKS_REFRESH_LOCK_TIMEOUT_SECONDS=2.0
```

`AUTH__CLIENT_ID` may remain set for backwards-compatible profile/resource-client context, but it is not the primary production acceptance control. Use `AUTH__AUDIENCE` for the API/resource-server audience and `AUTH__ALLOWED_AUTHORIZED_PARTIES` for allowed frontend/admin OAuth clients.

## Keycloak audience configuration

Configure Keycloak so access tokens issued to allowed clients contain the backend API audience:

1. Create or identify the backend API audience value, for example `fastapi-api`.
2. Add an audience mapper or client scope that includes that audience in access tokens.
3. Attach that client scope to the frontend/admin OAuth clients that are allowed to call the API.
4. Ensure those clients appear in the access token `azp` claim and list them in `AUTH__ALLOWED_AUTHORIZED_PARTIES`.
5. Keep ID tokens for client login/profile use only; do not send ID tokens to backend API endpoints.

## Startup metadata validation

When `AUTH__METADATA_VALIDATION=fail`, application startup validates the OIDC discovery document and JWKS before serving traffic:

- discovery payload is an object;
- discovery `issuer` exactly equals `AUTH__ISSUER_URL`;
- `jwks_uri` is present unless `AUTH__JWKS_URL` is explicitly configured;
- JWKS URI is HTTPS in staging/prod;
- advertised signing algorithms include `RS256` when the discovery field is present;
- JWKS payload is an object with a non-empty `keys` list;
- at least one RSA signing key exists;
- RSA signing keys contain `kid`.

`AUTH__METADATA_VALIDATION=warn` logs a warning without blocking startup and is intended for local/dev migration periods. `disabled` skips discovery/JWKS startup validation.

## JWKS cache and forced refresh cooldown

Normal JWT validation uses cached JWKS. On an unknown `kid`, the validator supports Keycloak key rotation by attempting a forced JWKS refresh, but that path is protected by a **JWKS forced refresh cooldown / singleflight protection**:

- at most one concurrent request performs the forced refresh;
- repeated unknown `kid` tokens during the cooldown reuse the existing cache and are rejected;
- the old JWKS cache is preserved if refresh fails;
- known-key tokens can continue to validate when a forced refresh fails.

This is not endpoint rate limiting; it is protection for the identity-provider metadata fetch path.

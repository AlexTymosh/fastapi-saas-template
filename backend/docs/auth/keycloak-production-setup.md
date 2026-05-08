# Keycloak Production Setup for Backend Authentication

## Resource server contract

The FastAPI backend acts as an OAuth2 Resource Server. Keycloak authenticates users and issues tokens; the backend validates Keycloak access tokens for this API before building an `AuthenticatedPrincipal` identity/profile boundary.

API clients must send **access tokens**, not ID tokens, in `Authorization: Bearer <access_token>`. Accepted tokens are treated as API access tokens, not as generic identity tokens.

Tenant and platform authorization remains local:

- tenant access comes from local organisation memberships;
- platform access comes from local `platform_staff` records;
- Keycloak realm/client roles are not the authorization source of truth for tenant/platform access.

## Required staging/prod environment

For `APP__ENVIRONMENT=staging` or `APP__ENVIRONMENT=prod`, the service refuses to start unless all of these are configured:

```bash
AUTH__ENABLED=true
AUTH__ISSUER_URL=https://keycloak.example.com/realms/<realm>
AUTH__AUDIENCE=fastapi-api
AUTH__ALLOWED_AUTHORIZED_PARTIES=fastapi-web,fastapi-admin
AUTH__METADATA_VALIDATION=fail
```

Additional production requirements:

- `AUTH__ISSUER_URL` must use HTTPS;
- explicit `AUTH__JWKS_URL`, when set, must use HTTPS;
- docs must be disabled;
- incoming request-id trust must be disabled unless implemented at a trusted edge;
- rate limiting must be enabled in-app or enforced by the edge;
- wildcard CORS origins are rejected.

`AUTH__CLIENT_ID` is retained only as backwards-compatible context for reading Keycloak `resource_access` data in identity mapping. It is not the primary production validation control.

## Audience and authorised party configuration

`AUTH__AUDIENCE` must match the API/resource-server audience in Keycloak access tokens. Configure Keycloak with an audience mapper or client scope so access tokens issued to frontend/admin clients contain the backend API audience.

`AUTH__ALLOWED_AUTHORIZED_PARTIES` lists OAuth clients allowed to call the API. The backend validates the access-token `azp` claim against this list when it is configured. Typical values are browser/admin clients such as:

```bash
AUTH__ALLOWED_AUTHORIZED_PARTIES=fastapi-web,fastapi-admin
```

## JWT validation rules

Runtime JWT validation enforces:

- RS256 only;
- `kid` header when `AUTH__REQUIRE_KID=true`;
- cached JWKS signing-key resolution;
- exact issuer match with `AUTH__ISSUER_URL`;
- audience match with `AUTH__AUDIENCE`;
- required `exp`, `iss`, `sub`, `aud` and, by default, `iat` claims;
- `azp` membership in `AUTH__ALLOWED_AUTHORIZED_PARTIES` when configured;
- maximum token lifetime bounded by `AUTH__MAX_TOKEN_LIFETIME_SECONDS`.

External authentication failures return a generic unauthorized response and must not expose token contents, raw claims, Authorization headers, JWKS payloads, or sensitive configuration.

## OIDC metadata validation

At startup, when auth is enabled and `AUTH__METADATA_VALIDATION` is not `disabled`, the backend fetches OIDC discovery from:

```text
AUTH__ISSUER_URL.rstrip("/") + "/.well-known/openid-configuration"
```

It validates issuer consistency, JWKS URI availability, HTTPS JWKS URI in staging/prod, RS256 support when advertised, and JWKS key shape. `AUTH__METADATA_VALIDATION=fail` raises a startup error; `warn` logs a safe warning and allows local/dev startup.

## JWKS caching and forced refresh cooldown

JWKS is cached by `AUTH__JWKS_CACHE_TTL_SECONDS`. Unknown `kid` misses support key rotation through a forced JWKS refresh, but the refresh path uses a JWKS forced refresh cooldown and singleflight protection:

- repeated unknown `kid` tokens do not spam Keycloak;
- concurrent misses result in at most one external forced refresh;
- existing valid JWKS cache is preserved if a refresh fails;
- after the cooldown, a newly rotated signing key can be picked up.

Relevant settings:

```bash
AUTH__JWKS_REFRESH_COOLDOWN_SECONDS=30.0
AUTH__JWKS_REFRESH_LOCK_TIMEOUT_SECONDS=2.0
```

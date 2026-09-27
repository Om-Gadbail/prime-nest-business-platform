# Tenant Context Flow (Prompt 2 — actual implementation)

A frontend `business_id` is a REQUESTED context selector. It is NEVER
authorization proof and NEVER selects a database. Every business-scoped
request follows this exact chain (enforced in code, verified by
`tests/test_prompt2_multibusiness.py`):

```
request (Bearer JWT: {sub, business_id?} — hint only)
  → authenticate_request: decode + load user → reject inactive (401)
  → if business_id claim: reload business + membership from DB
       → reject inactive/missing (403)
  → deps.require_permission(key): permission ∈ ctx.permissions?
       → _require_database_mapping: Business.database_key ∈ allowlist?
            → 403 on unknown/empty mapping (NO fallback database)
  → endpoint → BusinessResolver.for_staff (re-checks user/membership/
       business active + mapping) → frozen BusinessContext
  → service/repository filters by ctx.business_id
  → response scoped to ONE business
```

`BusinessContext` (`app/services/business_context.py`) carries:
`user_id`, `business_id`, `business_slug`, `external_business_id`,
`role_name`, `permissions`, **`database_key`**, `access_scope`.

## Database routing

```
BusinessContext.database_key  (from trusted registry row, never the request)
  → db_routing.normalize_database_key  (allowlist {platform_db, prime_db, nest_db})
  → Settings.database_url_for_key      (per-key URL or shared DATABASE_URL fallback)
  → independent per-key engine/pool    (app/core/db_routing.py)
  → request-scoped Session (closed in finally; never shared across tasks)
```

Co-located mode (default, today): all keys resolve to `DATABASE_URL` — one
physical database, row-level isolation, routing layer fully live.
Split mode (later): distinct `PLATFORM/PRIME/NEST_DATABASE_URL` — separate
databases/pools/credentials, zero code changes.

## Business switching (contract unchanged)

`POST /api/v1/auth/switch-business` accepts UUID or slug, verifies an ACTIVE
membership in an ACTIVE business, then issues a fresh token pair bound to the
new context. Arbitrary `business_id` values → 403. (`login` with
`business_slug` behaves identically.)

## Combined owner access (corrected in Prompt 2)

```
GET /api/v1/owner/combined?scope=all|<slug>
  → owner.combined.read + OWNER/ADMIN role
  → _authorized_business_ids: ACTIVE memberships ∩ ACTIVE businesses
  → aggregate ONLY granted businesses + audit (report.generated/owner_combined)
```

OLD (pre-Prompt-2): `scope=all` returned every active business in the
registry — a single-business OWNER could read unassigned businesses.
NEW: the grant set bounds the aggregation. See
`docs/owner-identity-and-membership.md`.

## Public intake (anonymous)

```
slug → normalize_slug → resolve_public_business (exists + active, else 404)
  → mapping check (else 404) → feature flag → write with server business_id
```

`/public/prime/*` writes Prime rows only; `/public/nest/*` Nest rows only.
No selector in body/query/header/path can override the slug.

## Worker / scheduler (no user context)

```
job {business_id}  (routing info, NOT authorization)
  → validate_business_job_scope: exists + active + valid mapping (else SKIP)
  → run_business_sweep on that business's key only
  → per-business commit/rollback; one failure never blocks others
```

`run_all_businesses` iterates the platform registry (active businesses) —
the same source the API uses. Scheduler tick leases stay global (coordination
only, not tenant data).

## Cache / Redis

Tenant data keys MUST be namespaced: `business:{business_id}:...`
(`db_routing.tenant_redis_key`). Current usage audit: public intake buckets
are per-IP+slug+endpoint; auth buckets per-IP+endpoint; Redis limiter keys
carry the `ratelimit:` prefix with the tenant-bearing bucket inside — no
shared bare key holds business data. No Redis redesign in Prompt 2 (by plan).

## Failure table (fail safely, no default tenant)

| Condition | Result |
|---|---|
| Unknown/empty `database_key` | 403 (staff) / 404 (public) / SKIP (worker) |
| Missing/revoked/suspended membership | 401/403, token re-validated per request |
| Inactive business | 403 (staff/switch) / 404 (public) |
| Unknown public slug | 404 |
| Forged JWT signature / forged `business_id` claim | 401 / 403 |
| Extra `business_id` in staff body | 422 (strict schemas reject it) |
| DB unreachable | `/ready` 503, sweep retries next tick |

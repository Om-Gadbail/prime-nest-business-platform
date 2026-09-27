# Final BusinessContext Contract (Prompt 3 — actual implementation)

`BusinessContext` is a frozen dataclass (`app/services/business_context.py`).
Downstream code may use ONLY these fields:

- `user_id`, `business_id` (UUIDs — stable identifiers; never change)
- `business_slug` (`prime` | `nest` | future), `external_business_id`
  (`prime-fitness-001` | `nest-library-001` | future)
- `business_name`, `role_name`, `permissions` (frozenset)
- `database_key` (`prime_db` | `nest_db`; from the trusted registry only)
- `access_scope` (`"business"`; reserved for future platform/combined scopes)
- `has(permission)` helper

## Canonical flow (every business-scoped request)

```
request (Bearer JWT {sub, business_id?} — hint only)
  → authentication (decode, HMAC) → user lookup → active check (401 otherwise)
  → membership lookup (user × business) → active check (403 otherwise)
  → business lookup → active check (403 otherwise)
  → permission resolution (role_permissions join; deny by default)
  → database mapping (Business.database_key ∈ {platform_db, prime_db, nest_db};
      unknown/empty → 403, NO fallback)
  → BusinessContext (frozen) → route/service → correct DB session
```

Enforcement points: `deps.require_permission` (140 gates) + mapping choke
point in `deps.py` + `BusinessResolver.for_staff` (re-checks all four) +
`for_public` (slug → registry → mapping → 404 otherwise).

## Vocabulary (NOT interchangeable)

- `business_id` = canonical internal identity. The JWT claim carries the UUID;
  the new stable `external_id` (`-001` keys) is for registry/ops reference.
- `slug` = public routing identifier (URLs, public intake, switch requests).
- `database_key` = trusted platform mapping (server-written; never a request
  input, never a credential, never derived from the slug at request time).

## Session contract (`app/api/deps.py`, `app/core/db_routing.py`)

- `get_db()` — request-scoped session (existing convention, kept).
- `get_platform_db()` — platform control-plane session (explicit alias).
- `get_business_db()` — business-operational session + verified context.
- Engine lifetime is application-scoped (per database key, independent pools);
  session lifetime is request/task-scoped, closed in `finally`, never shared
  across asyncio tasks/threads. Worker/scheduler sessions are independently
  managed per sweep. Commit/rollback ownership: services commit on success
  and roll back on failure; audit writes never roll back business data.

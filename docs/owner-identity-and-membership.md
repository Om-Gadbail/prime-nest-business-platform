# Owner Identity & Membership (Prompt 2 — actual implementation)

## One canonical identity

- Email: `owner@prime-nest-dashboard.com`
- Role: `OWNER` (via the EXISTING system role + RBAC matrix — no second RBAC)
- Home: the **platform identity layer** (`users` table, `platform_db` target).
  There is exactly one row — never one copy per business database.
- Credential: Argon2id hash only. Plaintext never touches the database, logs,
  or audit metadata (verified by test: hash starts with `$argon2`).
- The demo password `OwnerDemo123!` is a **development/demo bootstrap**
  (env `OWNER_SEED_PASSWORD`, default). Production refuses to seed the demo
  default — set a strong value. The owner can later change/reset the password,
  be deactivated, have sessions revoked, and gain/lose memberships through the
  normal user/membership paths. The identity is NOT hardcoded into any
  authorization branch.

## Explicit memberships

```
owner@prime-nest-dashboard.com  (ONE user row, platform)
  ├── membership(prime-fitness-001, OWNER, active, default) ──→ prime_db rows
  └── membership(nest-library-001, OWNER, active) ──→ nest_db rows
```

Seed: `ensure_platform_owner()` — idempotent (re-runs reuse the user row,
reuse memberships, and heal revoked/suspended rows back to active instead of
duplicating). Enabled by default (`seed_development(..., include_owner=True)`,
`SEED_PLATFORM_OWNER` kill-switch for operators).

## OWNER vs PLATFORM ADMIN

`OWNER` = full control **within granted businesses** (all permissions via the
matrix, including `owner.combined.read`). It is NOT a platform-admin grant:
there is no path from OWNER to registry/database-mapping writes, and every
cross-business read flows through the membership-bounded combined gate below.
No separate platform-admin role was needed for Prompt 2; if platform
administration appears later it must be a distinct role/permission, never an
implied OWNER power.

## Combined-view semantics change (Prompt 2 security fix)

OLD (pre-Prompt-2, `owner._resolve_combined_businesses`):
`scope=all` aggregated **every active business in the registry** for any
caller holding `owner.combined.read` + OWNER/ADMIN — including an OWNER whose
only membership was a single business (Attack #15, NEEDS VERIFICATION in the
Prompt 1 security audit). `test_block5_owner.py` even encoded it (nest-only
OWNER seeing Prime figures).

NEW: aggregation is bounded by `_authorized_business_ids` — ACTIVE memberships
∩ ACTIVE businesses, resolved server-side per request.

- `scope=all` → only granted businesses (owner Prime+Nest sees both;
  prime-only OWNER sees Prime alone).
- `scope=<slug>` → granted business only; known-but-unassigned → 403;
  unknown slug → 404.
- Future Business 3 is invisible until an explicit membership exists —
  "if user is owner, query every business" is gone by construction.
- Every combined read is audit-logged (`report.generated` /
  `owner_combined`, scope + slugs in meta — no secrets).

Updated tests: `test_block5_owner.py::test_combined_gating_and_content`
(prime-only OWNER sees Prime; `scope=nest` → 403),
`test_block57_e2e.py::test_combined_owner_e2e` (dual-membership owner sees
both), plus the Attack #15 matrix in `test_prompt2_multibusiness.py`.

## Permission posture (unchanged, re-verified)

- DB-backed, deny-by-default; `require_permission(...)` at 140 gates plus the
  new mapping choke point in `app/api/deps.py` (same 403 surface).
- Prime staff → Prime only; Nest staff → Nest only (404, no oracle).
- `leads.transfer` and `identity.cross-business` remain double-gated
  exceptional paths; they do not confer general cross-business access.

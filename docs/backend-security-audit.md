# Backend Security Audit (Prompt 1 — evidence-backed, no exaggeration)

Scope: `backend/` only. Every verdict cites the code or test that supports it.
Scale: PASS / WARNING / FAIL / NOT IMPLEMENTED / NEEDS VERIFICATION.

## Authentication

| Check | Verdict | Evidence |
|---|---|---|
| Password hashing (Argon2id, no custom/SHA schemes) | PASS | `core/security.py`: `PasswordHash.recommended()` (pwdlib/argon2); tests create users only via `hash_password` |
| Generic login failure (no email oracle) + dummy-verify timing | PASS | `services/auth.py:login`, `GENERIC_FAILURE`; `test_block1_auth.py` (13 passed) |
| Access-token lifetime bounded (1–1440 min, default 30) | PASS | `config.py` validators; HS256 allowlist HS256/384/512 |
| Refresh rotation + reuse family-kill + expiry | PASS | `services/auth.py:refresh`; `test_block1_auth.py::test_logout_revokes_session`, expired-token rejection passed |
| Refresh storage (hash-only, HttpOnly cookie scoped to `/api/v1/auth`) | PASS | `endpoints/auth.py` cookie kwargs; `auth_sessions` table |
| Token revocation (logout single-session; reuse kills family) | PASS | `auth.logout`, `session_repo.revoke/revoke_all_for_user` |
| Inactive/deleted users rejected on every request | PASS | `authenticate_request` re-loads user; `test_block1_*` inactive-user cases passed |
| Password validation | WARNING | Length-only (10–128). No complexity/breach-list rules — acceptable, but state it |
| Frontend `business_id`/`role`/`user_id` never trusted | PASS | Grep: zero client-`business_id` reads in endpoints; `deps.py` security-model docstring; membership re-checked per request |
| Logout/refresh behavior | PASS | Covered by tests; cookie cleared on logout |
| CORS (exact origins, no wildcard) | PASS | `main.py` + `effective_cors_origins`; dev fallback localhost only when non-prod and unconfigured |
| CSRF posture (cookie + Bearer) | WARNING | Refresh cookie is HttpOnly+SameSite (`lax` default) but the API also accepts Bearer, and state-changing staff calls use Bearer from memory — CSRF exposure is limited to cookie-only flows (`/auth/refresh`, which only mints tokens). No CSRF tokens. Acceptable for Bearer-primary SPA; revisit if cookie-authenticated mutations are added |
| Rate limiting on auth endpoints | PASS | `enforce_auth` bucket (30/300s default); Redis backend for multi-replica prod |

## Authorization / RBAC / business context

| Check | Verdict | Evidence |
|---|---|---|
| Roles/permissions DB-backed, deny-by-default | PASS | `models/rbac.py` matrix; 140 `require_permission` gates; `test_block1_rbac.py`, `test_block2_rbac.py`, `test_block3_rbac.py` (33 tests) passed |
| Least-privilege staff roles | PASS | MANAGER/STAFF/VIEWER explicit sets; `ADMIN` lacks `users.disable` |
| "Which businesses may this user access?" answered server-side | PASS | `login`/`switch-business` verify membership; `/auth/businesses` filters active only; `build_context` per request |
| Owner combined view double-gated | PASS | `owner.py` + `owner.combined_overview`: `owner.combined.read` AND OWNER/ADMIN role; `test_block5_owner.py` (6 passed) |
| Cross-business transfer double-gated + audited | PASS | `leads.py:transfer_lead`: `leads.transfer` AND OWNER/ADMIN + dual audit rows |
| AuthN vs AuthZ separated | PASS | `authenticate_request` (identity) vs `require_permission`/`BusinessAccessPolicy` (authorization) |

## Tenant isolation (15-attack review — code + test evidence, no live Postgres on this machine)

Covered by `test_block1_isolation.py` (9), `test_block2_isolation.py` (5),
`test_block3_isolation.py` (6), `test_block57_security.py` (6), `test_block2_security.py`
(11) — all passed on SQLite isolation fixtures. Mapping:

| # | Attack | Verdict | Basis |
|---|---|---|---|
| 1–2 | Nest↔Prime `business_id` swap | PASS | No client business_id consumed; context is JWT-hint + DB membership; isolation tests assert 404/403 cross-business |
| 3 | Staff changes another user's ID | PASS | Identity comes from Bearer `sub` only; no user-id params honored for auth |
| 4–6 | Cross-business customer/lead/membership IDs | PASS | `assert_same_business` → `NotFoundError` (404, no oracle); per-resource tests passed |
| 7–8 | Cross-business analytics / record mutation | PASS | All scoped to `ctx.business.id`; owner-combined is the only cross-business path and is double-gated |
| 9–11 | URL/query/body manipulation | PASS | Guards run on server context, not on supplied IDs (grep: no business_id params) |
| 12 | Header manipulation | PASS | Only `Authorization`/`Idempotency-Key`/`Content-Type` honored; none confer scope |
| 13 | JWT claim forgery | PASS | HMAC-signed; forged `business_id` fails membership lookup → 403 (`authenticate_request`) |
| 14 | Stale token after role/business change | PASS | Membership/role re-resolved per request; revoked/inactive → 401/403 without waiting for expiry |
| 15 | Owner reaches unassigned business | NEEDS VERIFICATION | Combined gate enforces role+permission, but scope-filtering by explicit grant list (`_resolve_combined_businesses`) was read, not executed against a live multi-business owner fixture here. Tests passed (6/6 owner) but a dedicated "owner with prime-only grant requests nest scope" case should be added in Prompt 2 |

## Public endpoint security

| Check | Verdict | Evidence |
|---|---|---|
| Anonymous usability preserved | PASS | `test_block2_public.py` (16), `test_block3_nest_public.py` (3) passed |
| Malformed input rejected | PASS | Pydantic schemas + `require_public_guard` (415 before parse); email-validator 422 observed live |
| Oversized payloads rejected pre-parse | PASS | `BodySizeLimitMiddleware` (header + streamed byte count, chunked-safe), 413 with request ID |
| Honeypot stays silent (fake success, nothing stored) | PASS | `_honeypot_hit` → `lead_id="received"`; security event logged |
| Rate limiting exists | PASS | `enforce_public` (20/600s default, per IP+slug+endpoint); WARNING: in-memory default — production multi-replica MUST set `REDIS_URL` (documented in `.env.example`, `config.py`, runbook) |
| Idempotency respected | PASS | `Idempotency-Key` acquire/replay/complete; concurrent-duplicate tests passed |
| Server-controlled business routing; forged slugs don't redirect data | PASS | `normalize_slug` + `resolve_public_business` (unknown/inactive → 404, no oracle); routing by slug only, never by client UUID |
| Feature flags fail safe | PASS | `require_feature` → 403 when disabled; advertised via public config |

## JWT / cookies / sessions

PASS (see Authentication). Notable: `jti` per access token (future revocation hook), cookie
`Path=/api/v1/auth` limits blast radius, `Secure`/`SameSite` env-configurable.

## Database isolation / sessions

| Check | Verdict |
|---|---|
| Per-request session, closed in `finally` (no cross-task reuse) | PASS (`core/database.py:get_db`) |
| Pool safety (`pool_pre_ping`, connect timeout) | PASS |
| Tenant separation at rest | WARNING — single shared DB; row-level isolation only. The 3-DB split is Prompt-2 work |
| Cross-DB transactions | NOT IMPLEMENTED (none needed; none exist) |

## Audit logging / security observability

PASS: `audit-events` API (`audit.read`), intake audit atomic with intake transaction,
auth failures + honeypot + rate-limit events via `security_event`, request IDs on 413s and
responses. Owner combined access is logged by contract (callers log `owner.combined`).

## Findings already covered by tests vs required next

- Present: auth, RBAC, isolation (25 tests), public abuse (19), refresh/reuse, concurrency
  (`test_block57_concurrency.py` 6 passed), full-platform integration (12 passed).
- Required next (Prompt 2): explicit owner-scope test (#15 above); Redis-backed limiter
  integration test in compose; live-DB smoke of `/ready` 200 path (here Postgres was absent
  so readiness-degraded 503 was verified instead — correct behavior, wrong environment for
  the happy path); multi-replica rate-limit verification.

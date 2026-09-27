# API Contract Finalization (Prompt 3)

Namespace `/api/v1` is canonical and frozen. No `/api/v2`. Route count: 160
(verified from `create_app()`; contract test asserts the anchor set).

## Requests

Domain-specific Pydantic v2 schemas with explicit types, `max_length` bounds,
required/optional discipline, and email/phone validation where appropriate.
Unknown fields are REJECTED (422) on strict schemas — a forged `business_id`
in a staff body fails closed instead of being honored. List inputs use
`list_params`: `limit` (default 50, clamped to max 100), `offset` (≥0),
`sort` (allowlisted per repository via `apply_sort` — arbitrary column names
never reach SQL), `direction` (`asc`/`desc`, defaults `desc`).

## Responses

Explicit response models (never raw ORM): stable field names, predictable
nullability, UUIDs as strings, money as decimal strings, datetimes ISO 8601
with offset. NEVER returned: passwords, hashes, refresh/access tokens in
bodies, secrets, internal DB URLs, stack traces. List responses use
`Page{T}` = `{items, total, limit, offset}` (totals always included; no
unbounded queries — server clamps).

## Errors (existing format, kept)

Body: `{"error": {"code": "...", "message": "..."}}`; `X-Request-ID` response
header (no body-shape change — the established contract wins over the sketch
in the plan). Status taxonomy: 400 service/validation-domain, 401
authentication, 403 authorization (incl. unmapped-tenant fail-closed), 404
not-found AND cross-tenant no-oracle (preserved deliberately — do not convert
to 403), 409 conflict/integrity, 413 body cap (pre-parse), 422 schema,
429 rate-limit (+ `Retry-After`), 502 provider, 503 disabled/dependency, 500
internal (generic message in production). No DB names, SQL, secrets, or
tenant-existence signals leak.

## Auth

`POST /auth/login` (email+password, optional `business_slug`; generic 401, no
email oracle) → `{user, business, membership, permissions, access_token,
refresh_token, token_type}`. `POST /auth/refresh` rotates (reuse kills the
family). `POST /auth/logout` revokes one session. `GET /auth/me` →
`{user, business|null, membership{role,status,is_default}|null, permissions[]}`.
`GET /auth/businesses` → bare list of
`{business, role, status, is_default}` (active grants only). `POST /auth/switch-business` (UUID or slug; membership-verified fresh
pair). Transport: Bearer + HttpOnly refresh cookie scoped to `/api/v1/auth`.

## Idempotency

Keys are tenant-scoped by construction: unique
`(business_id, endpoint, idem_key)` (`uq_idempotency_scope_key`) — one
business's key can never collide with another's. Coverage: public lead/
booking intake (`Idempotency-Key` acquire/replay/complete), payments and
membership mutations (service `idempotency_key` fields), messaging dedupe
(`business_id + provider_message_id`), scheduler execution dedupe
(`business_id + idempotency_key`). Retention: expired records purged by the
worker sweep.

## Public / staff (frozen)

Public: `GET config`, `POST leads`, `POST bookings`, `GET availability`,
`GET business-info`, `POST ai/chat` under `/public/{slug}/` (slug-routed,
rate-limited, honeypot-quiet, feature-flagged). Staff: all `/api/v1/<domain>`
routes follow authenticate → BusinessContext → permission → same-business
resource → correct DB. No path renames in Prompt 3.

## Backward compatibility

Zero breaking changes in Prompt 3. The single intentional behavior change in
the line (Prompt 2, carried): combined-owner aggregation bounded by explicit
memberships (OLD/NEW/WHY + migration notes in
`docs/owner-identity-and-membership.md`; affected tests updated, dashboard
compatible — its dual-membership owner still sees both businesses).

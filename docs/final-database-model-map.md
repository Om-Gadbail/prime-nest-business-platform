# Final Database Model Map (Prompt 3 — inspected from `Base.metadata`)

50 tables, 0 UNKNOWN, 0 DEPRECATED-in-use. Scope labels: **PLATFORM**
(control plane → `platform_db`) · **PRIME/NEST** (shared operational schema,
rows partitioned by `business_id` → `prime_db` / `nest_db`) · **GLOBAL-SHARED**
(explicitly cross-business-readable platform data).

No table is Prime-only or Nest-only: the operational schema is intentionally
shared so one codebase serves every business; isolation is by `business_id`
filtering from the verified `BusinessContext` today and by physical databases
after cutover. Primary keys are UUID (`uuid_pk`) everywhere except the two
composite join PKs noted below. All `DateTime` columns are timezone-aware;
no naive datetimes exist in the schema.

## PLATFORM → `platform_db` (11 tables)

| Table | Key relationships | Notes |
|---|---|---|
| `users` | none (identity root); email unique, normalized lowercase | ONE row per human; Argon2id hash only |
| `businesses` | none (tenant root); slug unique; `external_id` unique | Registry: `external_id` = canonical ID, `slug` = public route, `database_key` = trusted mapping. `state` column is UNUSED legacy (no code reads/writes it; kept, not dropped, per no-random-cleanup) |
| `business_memberships` | users, businesses, roles; unique (user_id, business_id) | The grant graph; status ∈ active/suspended/revoked |
| `auth_sessions` | users, businesses(nullable hint) | Refresh hash only; family revocation |
| `roles` | businesses(nullable; NULL = system role) | OWNER/ADMIN/MANAGER/STAFF/VIEWER + future per-business |
| `permissions` | none; key unique | ~70-key vocabulary |
| `role_permissions` | roles, permissions; composite PK (role_id, permission_id) | Deny-by-default matrix materialized |
| `business_relationships` | businesses (from/to; no `business_id` column) | Platform growth graph (Prime↔Nest cross-sell) |
| `persons` | none | Deduplicated human identity (cross-business match) |
| `identity_links` | businesses, contacts, persons, users | Explicitly gated cross-business read |
| `audit_events` | businesses(nullable), users; action/result vocabularies | Platform + business-scoped audit; secrets sanitized |

## PRIME/NEST → `prime_db` / `nest_db` by `business_id` (39 tables)

All carry non-nullable `business_id → businesses.id` with `ix_<table>_business_id`
(or named composite) indexes.

CRM: `leads`, `lead_activities`, `contacts`, `customers`, `bookings`
(requested→confirmed/cancelled/completed/no-show).
Membership commerce: `members`, `membership_plans` (NUMERIC price),
`memberships` (NUMERIC price/discount/final_amount), `renewals`
(NUMERIC renewal_amount), `payments` (NUMERIC amount; paid_at on `paid`),
`attendance`, `seats`, `seat_areas`, `seat_allocations`.
Work: `tasks`, `approvals`, `notifications`, `notification_preferences`
(composite PK user_id+business_id+notification_type).
Comms: `conversations`, `messages`, `message_delivery_events`,
`message_templates`, `communication_preferences`.
Automation/AI/growth: `automation_rules`, `automation_executions`,
`ai_conversations`, `ai_messages`, `ai_recommendations`, `ai_tool_calls`,
`ai_runs`, `growth_sources`, `attributions` (NUMERIC revenue),
`referrals`, `cross_sell_opportunities`, `analytics_snapshots`
(NUMERIC value), `daily_reports`, `domain_events`, `idempotency_records`
(unique `uq_idempotency_scope_key` on business_id+endpoint+idem_key).
Config: `business_settings` (one row per business; branding/operational JSON).

## GLOBAL-SHARED

No separate shared database. `persons`, `identity_links`,
`business_relationships` are PLATFORM tables with explicitly gated
cross-business reads (documented above) — not a third data plane.

## Cross-database foreign keys (post-split rule)

Postgres cannot enforce FKs across databases. After the physical split these
become application-level references with per-release orphan checks
(count/orphan reconciliation in `docs/database-migration-report.md`):

- Operational `business_id → businesses.id` (all 39 tables): immutable scope
  reference; verified per request via registry lookup, never trusted input.
- Operational `*_user_id → users.id` (assignees/actors/sessions): identity
  reference; access only through the auth/membership boundary, never free
  platform-user queries from business code.
- `identity_links.person_id/contact_id`, `persons` matches: only through
  the `identity.read`-gated service.
- No fake cross-database FK constraints were introduced; co-located mode
  keeps DB-level enforcement until cutover.

## Multi-database workflows (explicit, no distributed transactions)

1. **Owner combined read** (`GET /owner/combined`): sequential per-business
   aggregates over the grant set (read-only; no atomicity claim needed).
2. **Lead transfer** (`POST /leads/{id}/transfer`): linked COPY into the
   target business + audit note on the source; source row preserved. Today one
   transaction (co-located); post-split an application workflow (copy, verify,
   dual-audit) — never 2PC.
3. **Worker/scheduler sweeps**: per-business transactions; one business never
   blocks another. No cross-database transaction exists anywhere else.

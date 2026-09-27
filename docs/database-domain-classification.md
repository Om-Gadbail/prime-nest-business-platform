# Database Domain Classification (Prompt 2 — inspected, not assumed)

Method: `Base.metadata` dump of all 50 tables (column inventory + FK graph),
verified 2026-09-28 against `backend/app/models/*`. Every table below was
classified from its actual columns — `business_id` presence, FK targets, and
service-layer usage — never from its filename.

Domains: **PLATFORM** (control plane) · **PRIME-OPERATIONAL** / **NEST-OPERATIONAL**
(business rows, selected by `business_id`) · **GLOBAL-SHARED** (cross-business
by design) · **UNKNOWN** (none — every table is accounted for).

Target physical databases: `platform_db` · `prime_db` · `nest_db`.
Current physical database: single shared `app_db` (**co-located mode** — the
routing layer is live, the physical split cuts over via config; see
`docs/database-migration-report.md`).

Cross-database FK rule: after the physical split, FKs that cross the
platform/business boundary (`businesses.id` referenced from operational rows,
`users.id` referenced from operational rows) become **application-level
references with documented invariants** — Postgres cannot enforce FKs across
databases. In co-located mode the DB-level FKs below keep enforcing them.
No FK is dropped by migration 0008.

## PLATFORM — target `platform_db`

| Table | Business-scoped? | Cross-business? | Foreign keys | Migration strategy | Risk |
|---|---|---|---|---|---|
| `users` | No (identity is global; one row per human) | N/A (identity root) | none | stays in place; no move | Low |
| `businesses` | No (is the tenant root) | N/A (registry) | none | +3 registry columns (0008, additive); rows backfilled in place | Low |
| `business_memberships` | Platform-scoped grant (user↔business↔role) | Yes — the grant graph spans businesses | users, businesses, roles | stays in place; no move | Low |
| `auth_sessions` | No (session identity; `business_id` nullable context hint) | No | users, businesses | stays in place; no move | Low |
| `roles` | Platform (`business_id` NULL = system role; non-NULL reserved for future per-business roles) | No | businesses (nullable) | stays in place; no move | Low |
| `permissions` | No (global vocabulary) | No | none | stays in place; no move | Low |
| `role_permissions` | No (join) | No | permissions, roles | stays in place; no move | Low |
| `business_relationships` | No (`business_id` absent — pair rows, e.g. Prime↔Nest cross-sell) | Yes by design (platform growth graph) | businesses (from/to, no `business_id` col) | stays in place; no move | Low |
| `persons` | No (`business_id` absent — deduplicated human identity) | Yes by design (cross-business match) | none | stays in place; no move | Low |
| `identity_links` | Scoped row, platform read (`business_id` + person/contact/user links) | Yes — explicitly gated cross-business read | businesses, contacts, persons, users | stays in place; no move | Low |
| `audit_events` | Optional scope (`business_id` nullable; platform security events use NULL) | Read across scopes only via `audit.read` + explicit gates | businesses, users | stays in place; no move | Low |

## BUSINESS-OPERATIONAL — target `prime_db` / `nest_db` by `business_id`

All 38 tables below carry non-nullable `business_id -> businesses.id`
(`BusinessScopedMixin` or equivalent) and are filtered server-side from the
verified `BusinessContext`. No table moves physically in Prompt 2; the split
is a row-partition rehearsal (validated counts in the migration report).

| Table | FKs (all within-scope or platform refs) | Notes |
|---|---|---|
| `leads`, `lead_activities` | businesses, contacts, customers, users | Public intake writes here via slug→registry |
| `contacts`, `customers` | businesses, contacts | CRM vocab |
| `bookings` | businesses, contacts, customers, leads, users | |
| `members`, `membership_plans`, `memberships`, `renewals` | businesses, customers, members, membership_plans, memberships(self), users | Operational memberships (≠ `business_memberships` grants) |
| `payments` | businesses, customers, members, memberships, users | Money-hardened (0007) |
| `attendance` | businesses, members, memberships, seats, users | |
| `seats`, `seat_areas`, `seat_allocations` | businesses, seat_areas, members, memberships, users | Nest-heavy, shared model |
| `tasks` | businesses, users | |
| `notifications`, `notification_preferences` | businesses, users | |
| `approvals` | businesses, users | |
| `business_settings` | businesses | One row per business; feature flags |
| `automation_rules`, `automation_executions` | businesses, automation_rules, users | Worker executes per-business |
| `conversations`, `messages`, `message_delivery_events`, `message_templates`, `communication_preferences` | businesses, conversations, contacts, customers, leads | Comms/messaging |
| `ai_conversations`, `ai_messages`, `ai_recommendations`, `ai_tool_calls`, `ai_runs` | businesses, ai_conversations, leads | AI layer |
| `growth_sources`, `attributions`, `referrals`, `cross_sell_opportunities`, `analytics_snapshots` | businesses, leads | Growth/analytics source data |
| `daily_reports` | businesses | Scheduler-written owner briefs |
| `domain_events` | businesses, users | Automation event log |
| `idempotency_records` | businesses | Intake/mutation dedupe keys |

Platform references from operational rows (`users.id` assignees/actors,
`businesses.id` scope): enforced by DB FKs in co-located mode; become
application-level invariants after the physical split (verified per release
by the count/orphan checks in `docs/database-migration-report.md`).

## GLOBAL-SHARED

None beyond the platform tables above. There is no third category of data:
everything is either platform control-plane state or business-scoped rows.
(`persons`/`identity_links`/`business_relationships` are platform tables with
explicitly gated cross-business reads — not a separate database.)

## UNKNOWN

None. 50/50 tables classified.

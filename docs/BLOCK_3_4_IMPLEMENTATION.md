# Blocks 3 + 4 Implementation — Business Connections & Staff Dashboards

Steps 11–21. One shared FastAPI backend, one PostgreSQL database, Prime +
Nest as tenants, one shared dashboard codebase.

## 1. Architecture

```text
Prime website ─┐
               ├→ ONE FastAPI backend (/api/v1) → PostgreSQL
Nest website ──┘        │
                        ├─ shared business API layer (BusinessContext/Resolver/Policy)
                        ├─ lead routing (slug/intent/staff-transfer, audited)
                        ├─ unified identity (persons + per-business links, strict match)
                        ├─ tasks + notifications + audit events
                        └─ dashboard APIs (overview/summaries/activity/tasks/notifications)
                                   │
                    Shared staff dashboard (apps/staff-dashboard)
                    Prime config ↔ same code ↔ Nest config
```

Layering unchanged: `api → services → repositories → models`.
Routers hold no SQL; services hold no SQL; repositories own SQL.
Business scope always derives server-side (token context or verified
slug) — never from client `business_id`.

## 2. Step 11 — Nest website

The Nest website source was **not present in the workspace** (only
`prime-fitness-website` exists), so no existing site was rebuilt.
Delivered instead:

- `integrations/nest-website/backend.ts` — typed client (slug `nest`),
  12s timeout, `Idempotency-Key`, typed `BackendError`, honest
  request-received copy. Typechecks clean (`tsc --strict`, exit 0).
- `integrations/nest-website/attribution.ts` — UTM/referrer capture.
- `integrations/nest-website/forms.ts` — `saveNestEnquiry` /
  `saveNestVisit` adapters + `NEST_API_CONTRACT`.
- `integrations/nest-website/.env.example` + `README.md` (exact wiring).
- `docs/NEST_WEBSITE_INTEGRATION.md` — full contract.
- Backend proof: `tests/test_block3_nest_public.py` (nest lead/booking/
  config, visit stays REQUESTED, unknown slug 404) + 43 live Docker
  checks including Nest intake → Nest dashboard visibility.

Prime integration is untouched and still passing (backend public
contract is additive-only; live Prime intake re-verified).

## 3. Step 12 — Shared business API layer

- `app/services/business_context.py` — `BusinessContext` (deterministic
  per-request scope), `BusinessResolver.for_staff/for_public` (single
  verified paths), `BusinessAccessPolicy.require/require_any/
  require_role/assert_same_business` (deny by default),
  `BusinessScopedService` (search/pagination discipline).
- Consistent envelopes already standard: `Page{items,total,limit,offset}`
  (clamped 100), allowlisted sorts, `extra="forbid"` staff inputs,
  safe `{error:{code,message}}` + `X-Request-ID`, permission gates on
  every route, API versioned under `/api/v1`.
- Reusable endpoints serve both businesses (e.g. `GET /leads` uses token
  context; `POST /public/{slug}/leads` resolves the slug server-side).

## 4. Step 13 — Lead routing

`app/services/lead_routing.py` — explicit deterministic rules (no AI):

1. `slug` — verified slug owns the intake (Prime site → Prime).
2. `intent` — shared entry points route by keyword maps
   (`PRIME_INTENT_KEYWORDS` / `NEST_INTENT_KEYWORDS`); ties/zero-hits go
   to a configured default with a review reason, or raise explicitly.
3. `staff` — `POST /leads/{id}/transfer` (OWNER/ADMIN + `leads.transfer`):
   creates a linked copy in the target business, preserves the source,
   writes audit events in BOTH businesses. Reason ≥ 10 chars required.

`leads` gained `routed_by/routing_reason/routed_at` (migration 0004);
every intake stamps them. Tests: `tests/test_block3_routing.py`.

## 5. Step 14 — Unified identity

- Tables: `persons` (normalized phone/email only — no names/messages),
  `identity_links` (business, person, contact; unique per
  business+contact). Migration 0004.
- `app/services/identity.py` — strict equality matching only:
  both→`both`, one signal→`phone`/`email`, conflicting signals→keep
  separate (anchored on phone, conflict recorded), no signal→no link.
  No fuzzy merge, no silent deletes. Races surface as 409; retry reuses
  the winner (constraint-backed, same pattern as lead conversion).
- Auto-linked at intake/contact create/update (backfills old rows).
- Privacy: own-business slice needs `contacts.read`; cross-business
  overview needs `identity.read` (OWNER/ADMIN) and returns masked
  signals + per-business counts only — never contact rows.
- Manual linking: OWNER/ADMIN + audited. Tests:
  `tests/test_block3_identity.py` (cross-business link, family phone,
  ambiguity, manual-link gates, masking).

## 6. Step 15 — Isolation verification

`tests/test_block3_isolation.py` (adversarial, both directions): leads,
bookings, contacts, customers, tasks, activities, audit events,
notifications, identity, dashboard summaries, search/pagination/sort/
filter leakage, forged `business_id` (422), garbage UUIDs (404),
dual-membership token scoping, suspended-member lockout. Result: uniform
404 / safe 403, no oracles. Plus 43 live Docker checks replicating the
same guarantees on PostgreSQL.

## 7. Step 16 — Dashboard architecture

`apps/staff-dashboard` (React + TS + Vite + Tailwind + React Router +
TanStack Query + Zod + RHF + Lucide + Motion deps installed; Motion used
where useful):

- Shell: dark desktop sidebar, light content, header + breadcrumbs,
  mobile drawer + bottom nav (priority-ordered), business switcher,
  unread badge. Business name/accent from backend session (never
  ambiguous).
- Shared UI kit: Button/Card/Badge/StatusBadge, TableSkeleton,
  Empty/NoResults/Error/Forbidden states, Modal/Drawer/Confirm,
  TextInput/Select/TextArea/Pagination, Toasts.
- Server state: TanStack Query only; keys start with business id
  (`lib/query.ts`); mutations invalidate lists + overview + summaries.
- Centralized `lib/api.ts` (typed errors, one transparent refresh,
  graceful logout). No scattered fetch calls.
- Responsive: verified 360/768/1280 + 390/430/768/1024/1440/1920-safe
  fluid layouts (no fixed-width tables; stacked cards on mobile),
  ≥40px touch targets, visible focus, semantic controls, aria labels.

## 8. Steps 17/18 — Prime + Nest dashboards

Same routes, same modules, business resolved from the session:

Overview (KPIs, recent leads/activity, workload) · Leads (search,
filters, detail, timeline, notes, assign, status, convert, transfer) ·
Bookings (filters, detail, confirm/cancel/complete/no-show/**reopen**) ·
Contacts · Customers · Tasks (mine/overdue/completed, lifecycle) ·
Notifications (inbox, mark read/all, preferences) · Activity (audit
feed) · Settings (business info, intake flags — role-gated).

Prime shows Prime data with Prime branding; Nest shows Nest data with
Nest branding (accent, initials, switcher). Live-verified in a real
browser for both owners (Playwright `e2e/live.spec.ts`).

## 9. Step 19 — Roles & permissions

Additive matrix (Block 1/2 untouched):

| Capability | OWNER | ADMIN | MANAGER | STAFF | VIEWER |
|---|---|---|---|---|---|
| `dashboard.read` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `tasks.read/create/update` | ✓ | ✓ | ✓ | ✓ | read |
| `audit.read` | ✓ | ✓ | ✓ | ✓ | — |
| `leads.transfer` | ✓ | ✓ | — | — | — |
| `identity.read` | ✓ | ✓ | — | — | — |

Transfer + manual identity links additionally gate on the OWNER/ADMIN
**role** (defense in depth). Frontend hides; backend enforces. Tests:
`tests/test_block3_rbac.py` (parametrized matrix + seed-grant check).

## 10. Step 20 — Notifications + tasks

- No second notification system: new types `task_assigned` /
  `task_completed` reuse the Block 2 fan-out (preference-aware, deduped).
  Assignment notifies the assignee; completion notifies managers.
- `tasks` table + full lifecycle (`open→in_progress→completed|
  cancelled`, explicit reopen), priorities, due dates, assignee
  validation (active member of the SAME business), related-entity links
  validated same-business (else uniform 404). Filters: status, priority,
  assignee, overdue, due window, related type, search; pagination; audit
  on create/update/assign/status. Tests: `tests/test_block3_tasks.py`.

## 11. Step 21 — Audit / activity

- `audit_events` (append-only; no update/delete endpoints — 405).
  Actions allowlisted (`AUDIT_ACTIONS`), results `success/denied/error`.
- Captured: auth (login success/fail, logout, refresh, switch), lead
  (created incl. public intake, updated, assigned, status, note,
  converted, transferred both sides), booking (created, updated,
  status incl. reopen), contact/customer (created/updated), task
  lifecycle, notification preferences, business/settings updates,
  manual identity links.
- `meta` sanitized (sensitive keys dropped, values truncated);
  `log_event` never raises and (via `record_audit`) never rolls back
  business data. Audit rows are business-scoped; VIEWER denied.
- Tests: `tests/test_block3_audit.py` (creation, attribution, secrecy,
  scoping, append-only, filters).

## 12. Database changes (migration `0004_block3_tasks_audit_identity`)

New: `tasks`, `audit_events`, `persons`, `identity_links` (+ indexes on
`business_id` × status/assignee/due/created/actor/entity/action).
Altered: `leads` += `routed_by/routing_reason/routed_at`.
Data: 7 new permissions + role grants (hardcoded, idempotent).
Verified: `alembic upgrade head` on PostgreSQL (0003→0004), tables +
seed + grants confirmed live.

## 13. API changes (all additive)

New: `/tasks*`, `/audit-events*`, `/dashboard/*`, `/identity/*`,
`/leads/{id}/transfer`, `/bookings/{id}/reopen`.
Changed: `LeadOut` += routing lineage; intake stamps routing; contact
write paths auto-link identity; mutations emit audit rows. No breaking
changes (full Block 1+2 suite green).

## 14. Verification results

- Backend: **212 tests pass** (154 Block 1+2 + 58 new), Ruff clean.
- Frontend: typecheck clean, oxlint clean (1 RHF heuristic warning,
  same class as pre-existing), vitest **14/14**, production build clean.
- E2E: Playwright **12/12** (smoke ×3 viewports + live Prime/Nest
  sign-in ×3 viewports, overflow-checked).
- Live Docker: **43/43** API checks on PostgreSQL (intake, idempotency,
  honeypot, routing, transfer, identity, tasks, audit, dashboard,
  notifications, isolation, OpenAPI).
- Stack: rebuilt, healthy, migration applied, seed + grants verified.

## 15. Known limitations (real, not placeholders)

- Nest website wiring is a verified package, not a modified site (its
  source was absent). Remaining work is copy + env + handler hookup.
- Assignee pickers take a user UUID (no staff directory endpoint yet —
  next block can add `GET /users` for a dropdown).
- Task overdue is surfaced in UI/API, not pushed as notifications (no
  scheduler in this block; the `task_overdue` emission point is ready).
- Audit retention/purge is intentionally absent (append-only; ops
  decision for a later block).
- Rate limiter is still in-process (multi-worker prod needs Redis —
  pre-existing, unchanged).
- Migration `downgrade()` for 0004 is written but not exercised
  (upgrades are the supported path).

## 16. Next recommended block

**Block 5 — Memberships** (plans, billing lifecycle, seat/membership linkage):
the task/contact/customer/audit foundations it needs now exist
(`related_entity_*`, audited status machines, business settings flags).
Suggested order after that: payments → attendance/seats → owner command
center → analytics → WhatsApp automation.

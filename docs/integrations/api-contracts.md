# API Contracts — Blocks 5–7 (integration-ready, websites NOT connected yet)

Base URL: `VITE_API_BASE_URL` (e.g. `http://localhost:8000`).
All paths below are prefixed with `/api/v1`.
Auth: `Authorization: Bearer <access>` (staff/owner). Public intake needs
no auth. Errors: `{error: {code, message}}` + `X-Request-ID` header.
Pagination: `?limit=&offset=&sort=&direction=` → `{items, total, limit, offset}`.

## Conventions reused from Blocks 1–4

- Business scope comes from the authenticated token — clients never send
  `business_id`. Cross-business IDs yield uniform `404`.
- Mutations are audited; validation failures are `400/422`; state
  conflicts are `409`; permission failures are `403`.
- Money serializes as **strings** (`"1500.00"`) + `currency` code.
  Frontend never computes financial values.

## Owner (private — OWNER/ADMIN/MANAGER/VIEWER per permission)

| Method & path | Permission | Response |
|---|---|---|
| `GET /owner/overview?preset=&date_from=&date_to=&soon_days=` | `owner.dashboard.read` | `OwnerBusinessOverview` |
| `GET /owner/revenue?...` | `owner.dashboard.read` | `OwnerRevenueReport` (+ `daily_trend`) |
| `GET /owner/leads?...` | `owner.dashboard.read` | `OwnerLeadsReport` (+ `formulas`) |
| `GET /owner/combined?scope=all\|prime\|nest&...` | `owner.combined.read` + OWNER/ADMIN | `CombinedOverview` |

Presets: `today 7d 30d month quarter all`. Empty business → zeros.

## Members / Memberships / Plans / Renewals (private — staff)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /members?status=&search=` | `members.read` | paginated |
| `POST /members` | `members.create` | needs name/phone/email |
| `GET /members/{id}` | `members.read` | |
| `GET /members/{id}/profile` | `members.read` | member + current/history + payments + visits + seat |
| `PATCH /members/{id}` | `members.update` | allowlisted fields only |
| `GET /membership-plans?category=&is_active=&search=` | `membership_plans.read` | **future website plan list reads this** |
| `POST /membership-plans` | `membership_plans.manage` | unique `code` |
| `GET /membership-plans/{id}` | `membership_plans.read` | |
| `PATCH /membership-plans/{id}` | `membership_plans.manage` | bumps `version`; history safe |
| `GET /memberships?member_id=&status=&payment_state=&ending_before=&ending_after=` | `memberships.read` | |
| `POST /memberships` | `memberships.create` | price snapshot; `idempotency_key` supported |
| `GET /memberships/{id}` | `memberships.read` | |
| `POST /memberships/{id}/status` `{status, cancel_reason?}` | `memberships.update` | explicit transitions; reason required to cancel |
| `POST /memberships/{id}/renew` | `memberships.update` | new row + renewal link (history kept) |
| `GET /renewals?member_id=&status=&due_before=&due_after=` | `renewals.read` | pipeline |
| `POST /renewals` `{membership_id, due_date?, renewal_amount?, new_plan_id?}` | `renewals.create` | outreach record |
| `GET /renewals/{id}` | `renewals.read` | |

Membership `status` ∈ `pending active expired cancelled suspended`
(transition table enforced). `payment_state` is independent:
`unpaid pending partially_paid paid overdue failed refunded cancelled`.

## Payments (private — staff; refunds owner/admin)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /payments?member_id=&membership_id=&status=&method=` | `payments.read` | |
| `POST /payments` `{amount, method, member_id?, membership_id?, idempotency_key?}` | `payments.create` | always `pending` first; same key → same row |
| `GET /payments/{id}` | `payments.read` | `provider_ref` exposed; no secrets exist |
| `POST /payments/{id}/status` `{status}` | `payments.update` | staff confirms money; explicit transitions |
| `POST /payments/{id}/refund` `{reason≥5}` | `payments.refund` | PAID → REFUNDED; audited |

`method` ∈ `cash upi bank_transfer card online manual`.
`status` ∈ `pending paid failed cancelled refunded partially_paid overdue`.
Gateway webhooks: stubbed (`handle_webhook` records intent as pending;
**never auto-settles** until provider verification lands in Block 8).

## Attendance (private — staff)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /attendance?member_id=&day=&day_from=&day_to=&open_only=` | `attendance.read` | `day` = `YYYY-MM-DD` |
| `POST /attendance/check-in` `{member_id, attendance_date?, membership_id?, seat_id?, source?}` | `attendance.create` | same-day repeat → same row |
| `POST /attendance/{id}/check-out` | `attendance.create` | idempotent |
| `PATCH /attendance/{id}` `{notes?, source?, seat_id?}` | `attendance.update` | corrections only |

`source` ∈ `manual qr kiosk mobile rfid` (channels, no hardware yet).

## Seats (private — staff; reads feed future website availability)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /seat-areas` / `POST /seat-areas` | `seats.read` / `seats.manage` | floors/zones |
| `GET /seats?area_id=&status=&seat_type=&search=` | `seats.read` | |
| `GET /seats/availability` | `seats.read` | **server-computed** `{total, available, allocated_active, by_status}` |
| `GET /seats/available?seat_type=&area_id=` | `seats.read` | **future website seat picker reads this** |
| `POST /seats` / `GET /seats/{id}` / `PATCH /seats/{id}` | `seats.manage` / read | unique `seat_number` per business |
| `GET /seat-allocations?seat_id=&member_id=&status=` | `seats.read` | full history |
| `POST /seat-allocations` `{seat_id, member_id, membership_id?, notes?}` | `seats.manage` | exclusive; `409` when taken (incl. lost races) |
| `POST /seat-allocations/{id}/release` | `seats.manage` | history kept |
| `POST /seat-allocations/{id}/transfer` `{to_member_id}` | `seats.manage` | atomic release + re-allocate |

## Approvals (private)

| Method & path | Permission | Notes |
|---|---|---|
| `GET /approvals?status=&entity_type=` | `approvals.read` | |
| `POST /approvals` | `approvals.read` | any reader can **request** |
| `GET /approvals/{id}` | `approvals.read` | |
| `POST /approvals/{id}/decide` `{status, decision_note?}` | `approvals.manage` | requester cannot self-decide |

## Public (unchanged, reused by future websites)

- `POST /public/{slug}/leads`, `POST /public/{slug}/bookings`,
  `GET /public/{slug}/info` — Block 2 contracts still apply.
- No new public writes in Blocks 5–7. Future website plan/seat
  browsing reuses the **staff-read** catalogue endpoints behind a
  dedicated public read layer (to be built in the integration pass —
  staff APIs are never exposed publicly).

## Example payloads

```json
// POST /api/v1/memberships
{"member_id": "uuid", "plan_id": "uuid|null", "start_date": "2026-04-01",
 "end_date": null, "discount": "0.00", "notes": "", "idempotency_key": ""}

// POST /api/v1/payments
{"amount": "1999.00", "currency": "INR", "method": "upi",
 "member_id": "uuid", "membership_id": "uuid", "idempotency_key": "k-1"}

// POST /api/v1/attendance/check-in
{"member_id": "uuid", "seat_id": "uuid|null", "source": "manual"}

// POST /api/v1/seat-allocations
{"seat_id": "uuid", "member_id": "uuid", "membership_id": "uuid|null"}
```

## Error codes (HTTP status in parentheses)

`VALIDATION (400/422)`, `NOT_FOUND (404 — incl. cross-business)`,
`FORBIDDEN (403)`, `CONFLICT/DUPLICATE/INVALID_STATE (409)`
(seat taken, illegal transition, double refund, self-decision),
`PAYMENT_ERROR (409)`, `RATE_LIMITED (429)`.
Never: stack traces, SQL, secrets.

# API Enums & Statuses (Prompt 3 — harvested from `app/models/ops_vocab.py`)

Canonical rule: lowercase snake_case strings in BOTH database and API. No
`ACTIVE`/`active` duplicates, no `CANCELLED`/`CANCELED` duplicates were found.
Stored values are never silently renamed — any future rename ships with an
explicit migration mapping (none required today).

## Core lifecycle

- Leads: `new → contacted → qualified → booked → converted`, plus `lost`, `spam`
  (spam excluded from conversion eligibility — documented formula).
- Bookings: `requested → confirmed → completed`, plus `cancelled`, `no-show`
  (intake creates `requested` only).
- Operational memberships: `pending, active, suspended, cancelled, expired`
  (guarded transitions). Members/contacts/customers: `active, archived/inactive`.
- Membership grants (`business_memberships`): `active, suspended, revoked`.
- Businesses: `active, inactive` (+ `is_active` flag; both must agree).
- Payments: `pending, partially_paid, paid, overdue, failed, cancelled, refunded`
  (`paid_at` set on `paid`); methods: `upi, cash, card, bank_transfer, online, manual`.
- Renewals: `pending, confirmed, expired, cancelled`.
- Attendance: check-in/out records; sources `manual, kiosk, qr, rfid, mobile`.
- Seats: `available, reserved, occupied, blocked, maintenance`; allocations
  `active, reserved, released, transferred`.
- Tasks: `open, in_progress, completed, cancelled`; priorities `low, medium,
  high, urgent`.
- Approvals: `pending, approved, rejected, cancelled, expired`.
- Notifications: read/unread + per-type preferences.

## Platform / automation / AI / growth

- Auth audit: `auth.login_success/login_failed/refresh/logout/switch_business`.
- Security: `security.cross_business_denied`, `security.permission_denied`
  (results: `success, denied, error`).
- Automation executions: `pending, running, retrying, succeeded, failed, cancelled`.
- Comms: directions `inbound/outbound`; statuses
  `queued, sent, delivered, read, failed, undelivered`; channels
  `whatsapp, sms, email, in_app, web`.
- AI: conversations `active, resolved, closed, escalated`; recommendations
  `pending, approved, applied, rejected, expired`; runs
  `success, fallback, error, blocked`.
- Growth: sources `website, walk-in, google, instagram, whatsapp, referral,
  campaign, other`; referrals `pending, contacted, converted, expired, cancelled`;
  cross-sell `eligible, offered, consented, converted, declined, expired`.
- Roles: `OWNER, ADMIN, MANAGER, STAFF, VIEWER` (uppercase by design — role
  NAMES, not statuses; assignment always by `role_id` FK).

## Money / timestamps (canonical)

- Money: `NUMERIC(12,2)` (snapshots `14,2`); currency code column (INR
  supported; multi-currency capable); serialized as decimal STRINGS
  (`"3000.00"`) — never float. Rounding at write time via state machines.
- Timestamps: timezone-aware UTC internally (`DateTime(timezone=True)` on
  every timestamp column; zero naive columns in schema); API serializes ISO
  8601 with offset; business-local display (e.g. Asia/Kolkata) is a FRONTEND
  responsibility using the business `timezone` field.

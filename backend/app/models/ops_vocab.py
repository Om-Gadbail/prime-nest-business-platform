"""Shared operations vocabularies (Block 3/4).

Business-neutral value sets for staff tasks and the audit/activity system.
Stored as plain strings (SQLite/Postgres portable — no PG ENUMs).
Validation lives in schemas/services; these sets are the single source
of truth for allowed values.
"""

from __future__ import annotations

# Staff task lifecycle. Terminal states reopen explicitly via cancelled/open
# and completed/open (reopen), never silently.
TASK_STATUSES = frozenset({"open", "in_progress", "completed", "cancelled"})
TASK_PRIORITIES = frozenset({"low", "medium", "high", "urgent"})

# Allowed staff-side task transitions.
TASK_TRANSITIONS: dict[str, frozenset[str]] = {
    "open": frozenset({"in_progress", "completed", "cancelled"}),
    "in_progress": frozenset({"completed", "cancelled"}),
    "completed": frozenset({"open"}),  # explicit staff reopen only
    "cancelled": frozenset({"open"}),  # explicit staff reopen only
}

# Entity types a task may link to. Links are validated server-side: the
# referenced row must exist WITHIN the same business (else 404, no oracle).
TASK_RELATED_TYPES = frozenset(
    {
        "lead",
        "booking",
        "contact",
        "customer",
        # Blocks 5-7 operational entities (staff workflows link tasks to
        # members, memberships, payments, seats, renewals, approvals).
        "member",
        "membership",
        "payment",
        "seat",
        "seat_allocation",
        "renewal",
        "approval",
    }
)

# Append-only audit actions (Block 4, step 21). New actions may be added;
# never rename/remove (history must stay interpretable).
AUDIT_ACTIONS = frozenset(
    {
        "auth.login_success",
        "auth.login_failed",
        "auth.logout",
        "auth.refresh",
        "auth.switch_business",
        "lead.created",
        "lead.updated",
        "lead.assigned",
        "lead.status_changed",
        "lead.note_added",
        "lead.converted",
        "lead.transferred",
        "booking.created",
        "booking.updated",
        "booking.status_changed",
        "contact.created",
        "contact.updated",
        "customer.created",
        "customer.updated",
        "task.created",
        "task.updated",
        "task.assigned",
        "task.completed",
        "task.reopened",
        "notification.preference_changed",
        "settings.updated",
        "business.updated",
        "membership.created",
        "membership.updated",
        "identity.linked",
        "identity.person_matched",
        "security.cross_business_denied",
        "security.permission_denied",
        # Blocks 5-7 operational actions (append-only additions).
        # NOTE: "membership.created"/"membership.updated" already exist
        # (Block 4 staff business-membership actions) and are reused for
        # operational memberships; entity_type disambiguates
        # ("business_membership" vs "membership").
        "member.created",
        "member.updated",
        "membership.cancelled",
        "membership.renewed",
        "membership_plan.created",
        "membership_plan.updated",
        "membership_plan.archived",
        "payment.created",
        "payment.updated",
        "payment.paid",
        "payment.failed",
        "payment.refunded",
        "attendance.created",
        "attendance.checked_in",
        "attendance.checked_out",
        "attendance.corrected",
        "renewal.created",
        "renewal.updated",
        "renewal.confirmed",
        "seat.created",
        "seat.updated",
        "seat.allocated",
        "seat.released",
        "seat.transferred",
        "approval.requested",
        "approval.decided",
        # Blocks 8-12 additions (append-only).
        "automation.rule_triggered",
        "automation.executed",
        "automation.failed",
        "communication.sent",
        "communication.failed",
        "ai.conversation_started",
        "ai.tool_called",
        "ai.escalated",
        "growth.attributed",
        "referral.created",
        "referral.converted",
        "cross_sell.offered",
        "cross_sell.converted",
        "report.generated",
    }
)

AUDIT_RESULTS = frozenset({"success", "denied", "error"})

# Lead routing: how a lead was assigned to its owning business.
LEAD_ROUTED_BY = frozenset({"system", "slug", "intent", "staff", "default"})

# ---------------------------------------------------------------------------
# Blocks 5-7 operational vocabularies.
#
# Business-neutral value sets for members, memberships, payments, attendance,
# renewals, seats, approvals, and domain events. Stored as plain strings
# (SQLite/Postgres portable — no PG ENUMs). Validation lives in
# schemas/services; these sets are the single source of truth.
# ---------------------------------------------------------------------------

# Operational member profile lifecycle (distinct from staff BusinessMembership).
MEMBER_STATUSES = frozenset({"active", "inactive", "archived"})

# Operational membership lifecycle. Payment state is tracked separately on
# Membership.payment_state — never conflate the two.
OPERATIONAL_MEMBERSHIP_STATUSES = frozenset(
    {"pending", "active", "expired", "cancelled", "suspended"}
)

# Allowed operational membership transitions (staff-driven, explicit only).
OPERATIONAL_MEMBERSHIP_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"active", "cancelled"}),
    "active": frozenset({"expired", "cancelled", "suspended"}),
    "suspended": frozenset({"active", "cancelled", "expired"}),
    "expired": frozenset(),  # renewal creates a NEW membership row instead
    "cancelled": frozenset(),
}

# Denormalized payment state ON a membership (source of truth is payments).
MEMBERSHIP_PAYMENT_STATES = frozenset(
    {
        "unpaid",
        "pending",
        "partially_paid",
        "paid",
        "overdue",
        "failed",
        "refunded",
        "cancelled",
    }
)

# Membership plan catalogue. Categories are generic; businesses configure
# their own plan rows (see business_templates + seed data).
PLAN_CATEGORIES = frozenset(
    {"regular", "confirmed", "opening_regular", "opening_confirmed", "custom"}
)

# Provider-neutral payment lifecycle.
PAYMENT_STATUSES = frozenset(
    {
        "pending",
        "paid",
        "failed",
        "cancelled",
        "refunded",
        "partially_paid",
        "overdue",
    }
)

PAYMENT_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"paid", "failed", "cancelled", "partially_paid", "overdue"}),
    "partially_paid": frozenset({"paid", "failed", "cancelled", "overdue"}),
    "overdue": frozenset({"paid", "failed", "cancelled", "partially_paid"}),
    "failed": frozenset({"pending"}),  # explicit staff retry only
    "paid": frozenset({"refunded"}),
    "cancelled": frozenset(),
    "refunded": frozenset(),
}

# Payment collection channels (provider adapters plug in behind these names).
PAYMENT_METHODS = frozenset(
    {"cash", "upi", "bank_transfer", "card", "online", "manual"}
)

# Check-in capture channels (hardware integrations arrive later).
ATTENDANCE_SOURCES = frozenset({"manual", "qr", "kiosk", "mobile", "rfid"})

# Renewal pipeline.
RENEWAL_STATUSES = frozenset({"pending", "confirmed", "cancelled", "expired"})

RENEWAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"confirmed", "cancelled", "expired"}),
    "confirmed": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}

# Seat inventory.
SEAT_STATUSES = frozenset(
    {"available", "reserved", "occupied", "blocked", "maintenance"}
)
SEAT_TYPES = frozenset({"regular", "confirmed", "other"})

# Seat allocation lifecycle. Only ONE active allocation may exist per seat
# (partial unique index) and per member — enforced at the DB layer.
ALLOCATION_STATUSES = frozenset({"active", "reserved", "released", "transferred"})

# Owner approval/control foundation (extensible for automation + AI).
APPROVAL_STATUSES = frozenset(
    {"pending", "approved", "rejected", "cancelled", "expired"}
)
APPROVAL_ACTIONS = frozenset(
    {"approve", "reject", "review", "assign", "escalate", "confirm"}
)
APPROVAL_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending": frozenset({"approved", "rejected", "cancelled", "expired"}),
    "approved": frozenset(),
    "rejected": frozenset(),
    "cancelled": frozenset(),
    "expired": frozenset(),
}

# Domain events emitted by operational services (future Block 8 automation
# subscribes to these; services only emit, never consume).
# Blocks 8-12 extend the catalogue (additive only — never rename/remove).
DOMAIN_EVENTS = frozenset(
    {
        "lead.created",
        "lead.updated",
        "lead.contacted",
        "lead.converted",
        "booking.created",
        "booking.confirmed",
        "booking.completed",
        "booking.cancelled",
        "member.created",
        "membership.created",
        "membership.activated",
        "membership.expiring",
        "membership.expired",
        "membership.renewed",
        "membership.cancelled",
        "payment.created",
        "payment.recorded",
        "payment.paid",
        "payment.failed",
        "payment.overdue",
        "payment.refunded",
        "attendance.checked_in",
        "attendance.recorded",
        "attendance.checked_out",
        "seat.allocated",
        "seat.released",
        "seat.transferred",
        "renewal.created",
        "renewal.confirmed",
        "referral.created",
        "review.requested",
        "customer.inactive",
        "task.created",
        "task.overdue",
        "approval.requested",
        "approval.decided",
    }
)

# --- Blocks 8-12 vocabularies (automation / comms / AI / growth) ---

AUTOMATION_STATUSES = frozenset(
    {"pending", "running", "succeeded", "failed", "retrying", "cancelled"}
)

AUTOMATION_ACTION_TYPES = frozenset(
    {
        "send_message",
        "create_task",
        "create_notification",
        "schedule_followup",
        "request_review",
        "track_referral",
        "escalate",
        "ai_recommendation",
        "webhook_log",
    }
)

COMM_CHANNELS = frozenset({"whatsapp", "email", "sms", "in_app", "web"})
COMM_DIRECTIONS = frozenset({"inbound", "outbound"})
COMM_STATUSES = frozenset(
    {"queued", "sent", "delivered", "read", "failed", "undelivered"}
)
CONVERSATION_STATUSES = frozenset(
    {"open", "pending", "resolved", "escalated", "closed"}
)

AI_CONVERSATION_STATUSES = frozenset({"active", "resolved", "escalated", "closed"})
AI_MESSAGE_ROLES = frozenset({"visitor", "user", "assistant", "tool", "system"})
AI_RUN_STATUSES = frozenset({"success", "error", "blocked", "fallback"})
AI_RECOMMENDATION_STATUSES = frozenset(
    {"pending", "approved", "rejected", "applied", "expired"}
)
AI_RISK_LEVELS = frozenset({"low", "medium", "high"})

GROWTH_SOURCES_DEFAULT = (
    "website",
    "google",
    "instagram",
    "referral",
    "campaign",
    "walk-in",
    "whatsapp",
    "other",
)
REFERRAL_STATUSES = frozenset(
    {"pending", "contacted", "converted", "cancelled", "expired"}
)
CROSS_SELL_STATUSES = frozenset(
    {"eligible", "offered", "consented", "converted", "declined", "expired"}
)
ATTRIBUTION_SUBJECT_TYPES = frozenset(
    {"lead", "booking", "customer", "member", "membership", "payment"}
)

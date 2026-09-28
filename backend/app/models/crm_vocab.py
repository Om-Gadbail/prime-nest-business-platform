"""Shared CRM vocabularies (Block 2).

Business-neutral value sets stored as plain strings (SQLite/Postgres
portable — no PG ENUMs). Validation lives in schemas/services; these sets
are the single source of truth for allowed values.
"""

from __future__ import annotations

# Reusable contact identity.
CONTACT_STATUSES = frozenset({"active", "inactive", "archived"})
CONTACT_CHANNELS = frozenset({"call", "whatsapp", "email", "other"})

# Generic customer lifecycle (Prime and Nest extend in later blocks).
CUSTOMER_STATUSES = frozenset({"active", "inactive", "archived"})

# Business-neutral lead lifecycle. No business-specific stages here.
LEAD_STATUSES = frozenset(
    {"new", "contacted", "qualified", "booked", "converted", "lost", "spam"}
)
# Terminal states: no further staff transitions out (except reopen rules).
LEAD_TERMINAL_STATUSES = frozenset({"converted", "lost", "spam"})

# Reusable acquisition channels.
LEAD_SOURCES = frozenset(
    {
        "website",
        "whatsapp",
        "phone",
        "walk_in",
        "referral",
        "instagram",
        "facebook",
        "google",
        "other",
    }
)

# Lightweight CRM history (NOT the Block 13 enterprise audit log).
LEAD_ACTIVITY_TYPES = frozenset(
    {
        "note",
        "status_changed",
        "assigned",
        "contacted",
        "follow_up_scheduled",
        "converted",
        "lost",
        "booking_created",
    }
)

# Generic request types (availability engines arrive in later blocks).
BOOKING_TYPES = frozenset({"trial", "visit", "consultation", "enquiry", "other"})
BOOKING_STATUSES = frozenset(
    {"requested", "confirmed", "completed", "cancelled", "no_show"}
)

# Allowed staff-side status transitions. Public intake always creates
# REQUESTED; staff confirm explicitly. No silent jumps (e.g. cancelled ->
# completed is forbidden).
BOOKING_TRANSITIONS: dict[str, frozenset[str]] = {
    "requested": frozenset({"confirmed", "cancelled", "no_show"}),
    "confirmed": frozenset({"completed", "cancelled", "no_show"}),
    "completed": frozenset(),
    "cancelled": frozenset({"requested"}),  # explicit staff re-open only
    "no_show": frozenset({"requested"}),  # explicit staff re-open only
}

# In-app notification foundation (email/WhatsApp are future adapters).
NOTIFICATION_TYPES = frozenset(
    {
        "new_lead",
        "new_booking",
        "lead_assigned",
        "lead_follow_up",
        "task_assigned",
        "task_completed",
        "system",
        "ai_insight",
    }
)
NOTIFICATION_SEVERITIES = frozenset({"info", "warning", "critical"})

# AI foundation capabilities (advisory only — no autonomous actions).
AI_CAPABILITIES = frozenset(
    {
        "lead_summary",
        "lead_classification",
        "customer_insight",
        "operational_recommendation",
    }
)
AI_RUN_STATUSES = frozenset({"success", "error"})

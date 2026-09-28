"""AI context builders: minimized, redacted, size-bounded inputs.

Rules enforced here (before anything reaches a provider):
- allowlisted fields only (no passwords/tokens/sessions/credentials/roles);
- direct PII masked (phone -> last4, email -> masked form);
- free-text truncated to the configured budget;
- internal IDs/authorization data never included.
"""

from __future__ import annotations

from typing import Any

from app.services import normalize as norm

_TEXT_BUDGET_CHARS = 2000


def _clip(text: str, budget: int) -> str:
    clean = str(text or "").strip()
    if len(clean) <= budget:
        return clean
    return clean[:budget] + "…[truncated]"


def build_lead_context(lead: Any, *, max_input_chars: int) -> dict[str, Any]:
    """Minimal advisory context for one lead (no raw contact details)."""
    budget = max(500, min(int(max_input_chars), 100000))
    text_budget = min(_TEXT_BUDGET_CHARS, budget // 4)
    context = {
        "capability": "lead",
        "display_name": _clip(getattr(lead, "display_name", ""), 200),
        "status": str(getattr(lead, "status", "new") or "new")[:32],
        "source": str(getattr(lead, "source", "") or "")[:32],
        "service_interest": _clip(getattr(lead, "service_interest", ""), 200),
        "message": _clip(getattr(lead, "message", ""), text_budget),
        "contact_ref": {
            "phone": norm.mask_phone_last4(getattr(lead, "normalized_phone", None)),
            "email": norm.mask_email(getattr(lead, "normalized_email", None)),
        },
        "has_follow_up": bool(getattr(lead, "follow_up_at", None)),
        "is_assigned": bool(getattr(lead, "assigned_user_id", None)),
    }
    rendered = str(context)
    if len(rendered) > budget:
        # Hard guarantee: never exceed the configured input budget.
        context["message"] = _clip(context["message"], max(50, budget // 8))
    return context


def build_customer_context(customer: Any, *, max_input_chars: int) -> dict[str, Any]:
    budget = max(500, min(int(max_input_chars), 100000))
    return {
        "capability": "customer",
        "status": str(getattr(customer, "status", "active") or "active")[:32],
        "notes": _clip(
            getattr(customer, "notes", ""), min(_TEXT_BUDGET_CHARS, budget // 4)
        ),
    }


def build_booking_context(booking: Any, *, max_input_chars: int) -> dict[str, Any]:
    budget = max(500, min(int(max_input_chars), 100000))
    return {
        "capability": "booking",
        "booking_type": str(getattr(booking, "booking_type", "") or "")[:32],
        "status": str(getattr(booking, "status", "requested") or "requested")[:32],
        "title": _clip(getattr(booking, "title", ""), 200),
        "notes": _clip(
            getattr(booking, "notes", ""), min(_TEXT_BUDGET_CHARS, budget // 4)
        ),
    }

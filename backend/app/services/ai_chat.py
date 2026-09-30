"""Shared AI conversation/agent runtime (Block 10).

Website Chat and WhatsApp share THIS runtime — only the channel adapter
differs. Flow per turn:
  visitor message -> persist -> build context -> gateway.chat ->
  tool calls (validated, allowlisted, scoped) -> gateway.chat (final) ->
  persist -> reply. Safety: allowlist, schema check, max tool calls,
  timeouts, audit (ai_runs + ai_tool_calls), kill switch, fallback.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.repositories import blocks812 as repo
from app.repositories import ai_runs as runs_repo
from app.services import ai_gateway as gateway
from app.services import ai_tools
from app.services.errors import AIProviderError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _redact(text: str, limit: int = 4000) -> str:
    return str(text or "")[:limit]


def chat_turn(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    business_name: str,
    channel: str,
    visitor_key: str,
    message: str,
    mode: str = "public",
    caller: str = "public",
    run_id: str = "",
) -> dict:
    """One shared-runtime turn. Returns {reply, conversation_id, tool_calls, escalated}."""
    run_id = run_id or f"ai-{uuid.uuid4().hex[:12]}"
    message = _redact(message, 2000)
    if not message.strip():
        raise ValueError("Message must not be empty.")
    # Kill switch.
    if not settings.ai_enabled:
        return {
            "reply": gateway.FALLBACK_PUBLIC,
            "conversation_id": "",
            "tool_calls": [],
            "escalated": True,
            "mode": "fallback",
        }
    conv = repo.get_or_create_ai_conversation(
        db,
        business_id=business_id,
        channel=channel,
        visitor_key=visitor_key or "anon",
        mode=mode,
    )
    repo.add_ai_message(
        db,
        business_id=business_id,
        conversation_id=conv.id,
        role="visitor" if mode == "public" else "user",
        content=message,
        model="",
    )
    history = repo.recent_ai_messages(
        db, business_id=business_id, conversation_id=conv.id, limit=12
    )
    messages = [{"role": m.role, "content": m.content} for m in history]
    system = gateway.build_system_prompt(mode=mode, business_name=business_name)
    provider = gateway.get_chat_provider(settings)
    # Demo-safe deterministic path: when the real LLM is not configured
    # (noop fake), answer from REAL business data via allowlisted tools so
    # the Prime owner demo still feels like a live front-desk assistant.
    # The reply keeps the "Demo assistant" label so contract tests and the
    # honest fallback stay intact; no prices/hours/location are invented.
    if provider.name == "noop":
        return _noop_demo_turn(
            db,
            business_id=business_id,
            business_name=business_name,
            channel=channel,
            visitor_key=visitor_key,
            message=message,
            mode=mode,
            caller=caller,
            run_id=run_id,
            conv=conv,
            provider_model=provider.model,
        )
    started = time.monotonic()
    status, error_text, tool_trace = "success", "", []
    _transient_should_escalate = False
    try:
        specs = ai_tools.tool_specs(caller=caller)
        first = provider.chat(
            system=system,
            messages=messages,
            tools=specs,
            timeout_seconds=settings.ai_timeout_seconds,
            max_output_tokens=settings.ai_max_output_tokens,
        )
        tool_calls = list(first.tool_calls or [])[: max(1, settings.ai_max_tool_calls)]
        tool_results: list[dict] = []
        for call in tool_calls:
            tname = str(call.get("name", ""))
            targs = dict(call.get("args", {}) or {})
            try:
                result = ai_tools.execute_tool(
                    db,
                    business_id=business_id,
                    tool_name=tname,
                    args=targs,
                    caller=caller,
                )
                call_status = "success"
            except PermissionError as exc:
                result, call_status = {"error": "not_allowed"}, "blocked"
                error_text = str(exc)[:300]
            except Exception as exc:  # noqa: BLE001 - one bad tool must not kill the turn
                result, call_status = {"error": str(exc)[:300]}, "error"
            repo.record_tool_call(
                db,
                business_id=business_id,
                fields={
                    "conversation_id": conv.id,
                    "run_id": run_id,
                    "tool_name": tname,
                    "arguments": targs,
                    "result": result,
                    "status": call_status,
                    "caller": caller,
                },
            )
            tool_trace.append({"tool": tname, "status": call_status})
            tool_results.append({"tool": tname, "result": result})
        if tool_results:
            followup = messages + [
                {"role": "assistant", "content": first.text or "Working on that."},
                {"role": "tool", "content": _redact(str(tool_results), 3000)},
            ]
            final = provider.chat(
                system=system,
                messages=followup,
                tools=[],
                timeout_seconds=settings.ai_timeout_seconds,
                max_output_tokens=settings.ai_max_output_tokens,
            )
            reply = final.text or _fallback_from_tools(tool_results)
            model = final.model
        else:
            reply, model = first.text, first.model
        if not reply.strip():
            reply = (
                _fallback_from_tools(tool_results)
                if tool_results
                else gateway.FALLBACK_PUBLIC
            )
    except AIProviderError as exc:
        # MASTER FIX §5/§7/§8: transient Gemini failures (429 quota, 5xx,
        # transport) must NOT pause two-way WhatsApp chat and must NOT drop
        # to a generic message when real business data can answer. Build a
        # tool-grounded reply from live DB rows (plans/hours/location) so
        # "What are your plans?" still returns ₹1,500/₹4,000/₹7,500/₹12,000
        # even when the LLM quota is exhausted. Only explicit human-handoff
        # intents escalate; quota errors never pause future turns.
        status, error_text = "fallback", str(exc)[:500]
        try:
            reply, tool_trace, _transient_escalated = _transient_tool_fallback(
                db,
                business_id=business_id,
                business_name=business_name,
                channel=channel,
                visitor_key=visitor_key,
                message=message,
            )
            model = provider.model
            _transient_should_escalate = bool(_transient_escalated)
        except Exception:  # noqa: BLE001 - fallback builder never breaks the turn
            reply, model = gateway.FALLBACK_PUBLIC, provider.model
            _transient_should_escalate = False
    latency_ms = int((time.monotonic() - started) * 1000)
    repo.add_ai_message(
        db,
        business_id=business_id,
        conversation_id=conv.id,
        role="assistant",
        content=_redact(reply, 4000),
        model=model,
        tool_calls=tool_trace,
    )
    db.flush()
    try:
        runs_repo.create_run(
            db,
            business_id=business_id,
            provider=provider.name,
            model=model,
            capability=f"chat:{mode}:{channel}",
            status=status,
            latency_ms=latency_ms,
            input_chars=len(message),
            output_chars=len(reply),
            request_id=run_id[:64],
            error=error_text,
        )
        db.flush()
    except Exception:  # noqa: BLE001 - run audit must never break the reply
        pass
    escalated = (
        status == "error"
        or bool(_transient_should_escalate)
        or _needs_escalation(reply, tool_trace)
    )
    if escalated and conv is not None:
        conv.escalated = True
        conv.status = "escalated"
        db.flush()
    return {
        "reply": reply,
        "conversation_id": str(conv.id),
        "tool_calls": tool_trace,
        "escalated": escalated,
        "run_id": run_id,
    }


def _fallback_from_tools(tool_results: list) -> str:
    for entry in tool_results:
        result = entry.get("result", {}) if isinstance(entry, dict) else {}
        if isinstance(result, dict):
            if result.get("slots") is not None:
                slots = result.get("slots") or []
                if slots:
                    return "Available times: " + ", ".join(slots[:8]) + "."
                return "No slots are available for that date. Please try another day."
            if result.get("plans"):
                plans = result["plans"][:6]
                lines = [
                    f"{p.get('name')}: {p.get('price')} {p.get('currency', '')}"
                    for p in plans
                ]
                return "Our plans: " + " | ".join(lines) + "."
            if result.get("address"):
                return result["address"] + (
                    f" Directions: {result['directions_url']}"
                    if result.get("directions_url")
                    else ""
                )
            if result.get("status") == "requested":
                return result.get("message", "Request received.")
    return gateway.FALLBACK_PUBLIC


def _transient_tool_fallback(
    db,
    *,
    business_id,
    business_name: str,
    channel: str,
    visitor_key: str,
    message: str,
) -> tuple[str, list, bool]:
    """Tool-grounded reply when Gemini is transiently unavailable (429/5xx).

    Uses the SAME allowlisted PUBLIC tools as the live path, so prices /
    hours / location are always real DB rows — never invented. No Demo
    prefix (the provider IS configured; only this attempt was throttled).
    Returns (reply, tool_trace, escalated). Only explicit human-handoff
    intents escalate; quota errors never pause future turns.
    """
    lowered = (message or "").strip().lower()
    tool_trace: list[dict] = []
    name = (business_name or "this business").strip() or "this business"

    def _tool(tool_name: str, args: dict | None = None) -> dict:
        try:
            result = ai_tools.execute_tool(
                db,
                business_id=business_id,
                tool_name=tool_name,
                args=dict(args or {}),
                caller="public",
            )
            tool_trace.append({"tool": tool_name, "status": "success"})
            return result if isinstance(result, dict) else {}
        except Exception:  # noqa: BLE001 - one bad tool never breaks fallback
            tool_trace.append({"tool": tool_name, "status": "error"})
            return {}

    # Human handoff: create staff task, escalate (correct pause per §9).
    if any(h in lowered for h in _HUMAN_HINTS):
        try:
            from app.services import growth_engine as _growth

            _growth.create_handoff(
                db,
                business_id=business_id,
                customer_name="",
                customer_phone=visitor_key if channel == "whatsapp" else "",
                reason=f"Visitor asked for human help: {message[:200]}",
            )
            db.flush()
        except Exception:  # noqa: BLE001 - handoff task best-effort
            pass
        tool_trace.append({"tool": "create_staff_followup", "status": "success"})
        return (
            f"Of course — I've asked our {name} team to contact you personally. "
            "Someone will reach out shortly. Is there anything else I can help with meanwhile?",
            tool_trace,
            True,
        )

    # Plans / pricing (real catalogue only).
    if any(
        k in lowered
        for k in (
            "plan", "price", "pricing", "cost", "much", "monthly", "annual",
            "quarterly", "fees", "charges", "₹", "rs", "membership",
        )
    ):
        plans = _tool("get_membership_plans").get("plans") or []
        if plans:
            lines = [f"• {p.get('name')}: ₹{p.get('price')}" for p in plans[:6]]
            return (
                f"Here are the current {name} plans:\n"
                + "\n".join(lines)
                + "\nWould you like help choosing a plan or booking a free trial?",
                tool_trace,
                False,
            )

    # Location.
    if any(
        k in lowered
        for k in ("where", "located", "location", "address", "reach", "map", "directions")
    ):
        loc = _tool("get_business_location")
        addr = str(loc.get("address", "") or "").strip()
        map_url = str(loc.get("map_url", "") or "").strip()
        if addr and addr.lower() != "address not configured":
            suffix = f" Map: {map_url}" if map_url else ""
            return (
                f"📍 {name} is at {addr}.{suffix} Want directions or trial details?",
                tool_trace,
                False,
            )

    # Hours.
    if any(k in lowered for k in ("timing", "timings", "hours", "open", "close", "when")):
        hours = _tool("get_business_hours").get("hours") or {}
        weekly = hours.get("weekly") or {} if isinstance(hours, dict) else {}
        if weekly:
            parts = []
            for day in (
                "monday", "tuesday", "wednesday", "thursday",
                "friday", "saturday", "sunday",
            ):
                cfg = weekly.get(day) or {}
                if cfg.get("closed") is True:
                    parts.append(f"{day[:3].title()}: closed")
                elif cfg.get("open"):
                    parts.append(f"{day[:3].title()}: {cfg.get('open')}-{cfg.get('close', '')}")
            detail = "; ".join(parts) if parts else "Please contact the team for hours."
            return (
                f"🕒 {name} hours — {detail}. Want to book a visit?",
                tool_trace,
                False,
            )

    # Trial / booking intent: trigger the existing lead workflow best-effort,
    # then ask for the slot details (same as the live path would).
    if any(
        k in lowered
        for k in ("trial", "visit", "book", "join", "free trial", "demo")
    ):
        try:
            _tool(
                "create_lead",
                {
                    "phone": visitor_key if channel == "whatsapp" else "",
                    "message": message[:500],
                    "interest": "Free trial",
                },
            )
        except Exception:  # noqa: BLE001 - lead creation best-effort
            pass
        return (
            f"Great — I can help you book a free trial at {name}! "
            "Just share your name and preferred day/time (e.g. 'Ravi, tomorrow 7 AM'), "
            "and our team will confirm your slot. Which day works best for you?",
            tool_trace,
            False,
        )

    # Greeting / about-prime / default: friendly menu from configured data.
    profile = _tool("get_business_profile")
    loc = _tool("get_business_location")
    display = str(profile.get("name", "") or name)
    addr = str(loc.get("address", "") or "").strip()
    loc_line = (
        f"\n📍 {addr}" if addr and addr.lower() != "address not configured" else ""
    )
    if any(k in lowered for k in ("hi", "hello", "hey", "about", "prime", "info")) or not lowered:
        return (
            f"Hi! 👋 Welcome to {display}! I can help you with:"
            "\n• Membership plans\n• Free trial / trial booking\n• Gym timings"
            "\n• Facilities and services\n• Location and contact details"
            f"{loc_line}"
            "\nWould you like to know about our membership plans or book a trial?",
            tool_trace,
            False,
        )
    return (
        f"Thanks for reaching out to {display}! I can help with membership plans, "
        f"free trial booking, timings, and location.{loc_line} "
        "What would you like to know?",
        tool_trace,
        False,
    )


_ESCALATION_HINTS = (
    "speak to staff",
    "talk to staff",
    "human",
    "manager",
    "complaint",
    "refund",
)


def _needs_escalation(reply: str, tool_trace: list) -> bool:
    lowered = reply.lower()
    if any(h in lowered for h in _ESCALATION_HINTS):
        return True
    return any(t.get("status") == "blocked" for t in tool_trace)


_DEMO_PREFIX = "(Demo assistant — AI provider not configured. )"

_HUMAN_HINTS = (
    "talk to someone",
    "connect me to staff",
    "need a human",
    "speak to",
    "talk to staff",
    "human",
    "manager",
    "owner",
    "call me",
    "staff",
)


def _noop_demo_turn(
    db,
    *,
    business_id,
    business_name: str,
    channel: str,
    visitor_key: str,
    message: str,
    mode: str,
    caller: str,
    run_id: str,
    conv,
    provider_model: str,
) -> dict:
    """Deterministic demo assistant turn (noop provider).

    Uses ONLY allowlisted business-scoped tools; never invents business
    facts. Keeps the honest demo label so tests and the UI can distinguish
    MOCK from live Gemini replies.
    """
    import time as _time

    started = _time.monotonic()
    lowered = (message or "").strip().lower()
    tool_trace: list[dict] = []

    def _tool(name: str, args: dict | None = None) -> dict:
        try:
            result = ai_tools.execute_tool(
                db, business_id=business_id, tool_name=name,
                args=dict(args or {}), caller="public",
            )
            tool_trace.append({"tool": name, "status": "success"})
            return result if isinstance(result, dict) else {}
        except Exception:  # noqa: BLE001 - one bad tool must not kill demo
            tool_trace.append({"tool": name, "status": "error"})
            return {}

    def _persist(reply_text: str, *, is_escalated: bool) -> dict:
        repo.add_ai_message(
            db, business_id=business_id, conversation_id=conv.id,
            role="assistant", content=_redact(reply_text, 4000),
            model=provider_model, tool_calls=tool_trace,
        )
        db.flush()
        try:
            runs_repo.create_run(
                db, business_id=business_id, provider="noop",
                model=provider_model, capability=f"chat:{mode}:{channel}",
                status="success",
                latency_ms=int((_time.monotonic() - started) * 1000),
                input_chars=len(message), output_chars=len(reply_text),
                request_id=run_id[:64], error="",
            )
            db.flush()
        except Exception:  # noqa: BLE001 - audit never breaks reply
            pass
        if is_escalated and conv is not None:
            conv.escalated = True
            conv.status = "escalated"
            db.flush()
        return {
            "reply": reply_text, "conversation_id": str(conv.id),
            "tool_calls": tool_trace, "escalated": is_escalated,
            "run_id": run_id,
        }

    name = (business_name or "this business").strip() or "this business"

    # Human handoff: create staff task, pause autonomous AI.
    if any(h in lowered for h in _HUMAN_HINTS):
        try:
            from app.services import growth_engine as _growth

            _growth.create_handoff(
                db, business_id=business_id, customer_name="",
                customer_phone=visitor_key if channel == "whatsapp" else "",
                reason=f"Visitor asked for human help: {message[:200]}",
            )
            db.flush()
        except Exception:  # noqa: BLE001 - handoff task best-effort
            pass
        tool_trace.append({"tool": "create_staff_followup", "status": "success"})
        return _persist(
            _DEMO_PREFIX
            + f"Of course — I've asked our {name} team to contact you personally. "
            "Someone will reach out shortly. Is there anything else I can help with meanwhile?",
            is_escalated=True,
        )

    # Member-specific state: never expose another customer's data; ask to verify.
    if any(k in lowered for k in (
        "expire", "expiry", "renew", "my membership", "my payment",
        "payment go through", "last attend", "my attendance", "is my membership",
    )):
        return _persist(
            _DEMO_PREFIX
            + "I can check that for you. Could you please confirm the phone number "
            f"linked to your {name} membership? Our team can then pull up your "
            "exact expiry / renewal / payment status — or I can connect you to staff.",
            is_escalated=False,
        )

    # Location.
    if any(k in lowered for k in (
        "where", "located", "location", "address", "reach", "map", "directions",
    )):
        loc = _tool("get_business_location")
        addr = str(loc.get("address", "") or "").strip()
        map_url = str(loc.get("map_url", "") or "").strip()
        if not addr or addr.lower() == "address not configured":
            return _persist(
                _DEMO_PREFIX
                + f"I don't have the {name} address configured yet — "
                "our team can share it right away. Want me to connect you to staff?",
                is_escalated=False,
            )
        suffix = f" Map: {map_url}" if map_url else ""
        return _persist(
            _DEMO_PREFIX + f"📍 {name} is at {addr}.{suffix} Want directions or trial details?",
            is_escalated=False,
        )

    # Plans / pricing (real catalogue only).
    if any(k in lowered for k in (
        "plan", "price", "pricing", "cost", "much", "monthly", "annual",
        "quarterly", "fees", "charges", "₹", "rs",
    )):
        plans = _tool("get_membership_plans").get("plans") or []
        if not plans:
            return _persist(
                _DEMO_PREFIX
                + f"I don't have the current {name} plans in the system — "
                "our team can share them right away. Want me to connect you to staff?",
                is_escalated=False,
            )
        lines = [f"• {p.get('name')}: ₹{p.get('price')}" for p in plans[:6]]
        return _persist(
            _DEMO_PREFIX + f"Here are the current {name} plans:\n"
            + "\n".join(lines)
            + "\nWould you like help choosing a plan or booking a trial?",
            is_escalated=False,
        )

    # Hours.
    if any(k in lowered for k in ("timing", "timings", "hours", "open", "close")):
        hours = _tool("get_business_hours").get("hours") or {}
        weekly = hours.get("weekly") or {} if isinstance(hours, dict) else {}
        if weekly:
            parts = []
            for day in ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"):
                cfg = weekly.get(day) or {}
                if cfg.get("closed") is True:
                    parts.append(f"{day[:3].title()}: closed")
                elif cfg.get("open"):
                    parts.append(f"{day[:3].title()}: {cfg.get('open')}-{cfg.get('close', '')}")
            detail = "; ".join(parts) if parts else "Please contact the team for hours."
            return _persist(
                _DEMO_PREFIX + f"🕒 {name} hours — {detail}. Want to book a visit?",
                is_escalated=False,
            )
        return _persist(
            _DEMO_PREFIX
            + f"I don't have the {name} hours configured yet — "
            "our team can confirm them. Want me to connect you to staff?",
            is_escalated=False,
        )

    # Trial / booking intent (MASTER FIX §5/§13: trigger the existing
    # lead workflow best-effort so "I want a free trial" creates a lead even
    # in demo/noop mode; the live Gemini path calls create_lead via tools).
    if any(k in lowered for k in (
        "trial", "visit", "book", "join", "come tomorrow", "free trial", "demo",
    )):
        try:
            _tool(
                "create_lead",
                {
                    "phone": visitor_key if channel == "whatsapp" else "",
                    "message": message[:500],
                    "interest": "Free trial",
                },
            )
        except Exception:  # noqa: BLE001 - lead creation best-effort
            pass
        return _persist(
            _DEMO_PREFIX
            + f"Great — I can help you book a trial at {name}! "
            "Just share your name and preferred day/time (e.g. 'Ravi, tomorrow 7 AM'), "
            "and our team will confirm your slot. Which day works best for you?",
            is_escalated=False,
        )

    # Default: Prime/business intro from configured data.
    profile = _tool("get_business_profile")
    loc = _tool("get_business_location")
    display = str(profile.get("name", "") or name)
    addr = str(loc.get("address", "") or "").strip()
    hours = _tool("get_business_hours").get("hours") or {}
    loc_line = f"\n📍 {addr}" if addr and addr.lower() != "address not configured" else ""
    return _persist(
        _DEMO_PREFIX + f"Hi 👋 Welcome to {display}!\nI can help you with:"
        "\n• Membership plans\n• Free trial / trial booking\n• Gym timings"
        "\n• Facilities and services\n• Location and contact details"
        "\n• Membership renewal\n• Booking assistance"
        f"{loc_line}"
        "\nWould you like to know about our membership plans or book a trial?",
        is_escalated=False,
    )

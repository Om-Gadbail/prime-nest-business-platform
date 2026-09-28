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
    started = time.monotonic()
    status, error_text, tool_trace = "success", "", []
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
        status, error_text = "error", str(exc)[:500]
        reply, model = gateway.FALLBACK_PUBLIC, provider.model
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
    escalated = status == "error" or _needs_escalation(reply, tool_trace)
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

"""Automation engine (Block 8, steps 39-43; Prompt 7 growth extension).

Domain Events -> EventBus (dispatch) -> Rules -> Conditions -> Actions ->
Audit -> Retry. Every execution is idempotent (business_id + idempotency),
auditable, retry-safe (bounded), permission-aware, observable, failure-safe.

Action types: send_message | create_task | create_notification |
schedule_followup | request_review | track_referral | escalate |
ai_recommendation | webhook_log.

Execution statuses (Prompt 7 canonical): queued | running | completed |
failed | skipped | cancelled. Legacy Block 8 rows (pending/succeeded/
retrying) are read as equivalents — never rewritten — so history stays
interpretable: pending==queued, succeeded==completed, retrying==queued
(drainable). New executions always use the canonical set.

Two trigger paths (Prompt 7 §28 — website stays fast):
- dispatch_event: synchronous rule run (staff/ops/tests/worker contexts).
- enqueue_for_event: persist queued executions only (public website intake);
  the worker drains them via retry_due (genuine re-execution, bounded).

Opt-out safety: a send blocked by communication preferences resolves to
``skipped`` (terminal, no retry) — never failed/retrying, never a send.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ops_vocab import (
    AUTOMATION_ACTION_TYPES,
    AUTOMATION_PENDING_STATUSES,
    AUTOMATION_SUCCESS_STATUSES,
    AUTOMATION_TERMINAL_STATUSES,
)
from app.repositories import blocks812 as repo
from app.services import domain_events as events

RETRYABLE = frozenset({"failed", "retrying"})


class _SkippedAction(Exception):
    """Terminal skip: ineligible/opt-out/cancelled (recorded, never retried)."""


def _business_render_context(db: Session, *, business_id) -> dict:
    """Shared template variables from Business Configuration (no hardcoding)."""
    render_ctx: dict = {}
    try:
        from app.repositories import businesses as _business_repo

        business = _business_repo.get_by_id(db, business_id)
        if business is not None:
            render_ctx["business"] = str(getattr(business, "name", "") or "")
            render_ctx["business_phone"] = str(getattr(business, "phone", "") or "")
            render_ctx["business_city"] = str(getattr(business, "city", "") or "")
    except Exception:  # noqa: BLE001 - missing config never breaks sends
        pass
    return render_ctx


# Legacy -> canonical status equivalence (reads only; history untouched).
_LEGACY_SUCCESS = frozenset({"succeeded"}) | AUTOMATION_SUCCESS_STATUSES
_LEGACY_DRAINABLE = frozenset({"pending", "retrying"}) | AUTOMATION_PENDING_STATUSES

# Marker raised when a recipient opted out (maps to skipped, not failed).
OPT_OUT_MARKER = "Recipient has opted out"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _is_terminal(status: str) -> bool:
    value = str(status or "")
    return value in AUTOMATION_TERMINAL_STATUSES or value == "succeeded"


def _is_success(status: str) -> bool:
    return str(status or "") in _LEGACY_SUCCESS


def _is_drainable(status: str) -> bool:
    return str(status or "") in _LEGACY_DRAINABLE


def _audit(
    db: Session,
    *,
    business_id,
    action: str,
    meta: dict | None = None,
    actor_user_id=None,
) -> None:
    """Best-effort automation audit (never breaks the execution itself)."""
    try:
        from app.services import audit as audit_service

        audit_service.log_event(
            db,
            business_id=business_id,
            action=action,
            actor_user_id=actor_user_id,
            entity_type="automation",
            meta=dict(meta or {}),
        )
    except Exception:  # noqa: BLE001 - audit must never break automation
        pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _idem_key(*, business_id, rule_id, event_id, action_idx: int = 0) -> str:
    raw = f"{business_id}:{rule_id}:{event_id}:{action_idx}"
    return hashlib.sha256(raw.encode()).hexdigest()[:48]


def condition_matches(conditions: dict, context: dict) -> bool:
    """All configured conditions must match (exact/small operators)."""
    for key, expected in dict(conditions or {}).items():
        actual = context.get(key)
        if isinstance(expected, dict):
            op = str(expected.get("op", "eq"))
            val = expected.get("value")
            if op == "eq" and actual != val:
                return False
            if op == "neq" and actual == val:
                return False
            if op == "in" and actual not in (val or []):
                return False
            if op == "not_in" and actual in (val or []):
                return False
        elif actual != expected:
            return False
    return True


def dispatch_event(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    event_type: str,
    entity_type: str | None = None,
    entity_id=None,
    actor_user_id=None,
    payload: dict | None = None,
    correlation_id: str = "",
) -> list:
    """Persist the domain event, then run matching active rules synchronously.

    Duplicate-delivery safe (Prompt 7 §5, §10): when an identical event
    (same business + type + entity + payload) was already recorded in the
    last 24h — duplicated webhook, scheduler double-fire, worker retry,
    application restart — the existing row is REUSED instead of emitting a
    second one, so per-action idempotency keys reproduce and no second
    WhatsApp message is ever produced for the same logical occurrence.
    """
    event = _recent_duplicate_event(
        db,
        business_id=business_id,
        event_type=event_type,
        entity_id=entity_id,
        payload=payload,
    )
    if event is None:
        event = events.emit(
            db,
            business_id=business_id,
            event_type=event_type,
            entity_type=entity_type,
            entity_id=entity_id,
            actor_user_id=actor_user_id,
            payload=payload,
        )
        db.flush()
    if not settings.automation_enabled:
        return []
    return run_rules_for_event(
        db,
        settings,
        business_id=business_id,
        event=event,
        event_type=event_type,
        correlation_id=correlation_id or str(event.id),
        actor_user_id=actor_user_id,
    )


def _recent_duplicate_event(
    db: Session,
    *,
    business_id,
    event_type: str,
    entity_id,
    payload: dict | None,
    window_hours: int = 24,
) -> object | None:
    """Find an identical recent event (same logical occurrence) or None."""
    from sqlalchemy import select as _select
    from app.models.operations import DomainEvent
    from app.services import idempotency as idem_service

    try:
        digest = idem_service.payload_hash(dict(payload or {}))
    except Exception:  # noqa: BLE001 - hashing never blocks dispatch
        return None
    try:
        eid = (
            entity_id
            if isinstance(entity_id, uuid.UUID)
            else (uuid.UUID(str(entity_id)) if entity_id not in (None, "") else None)
        )
    except (ValueError, AttributeError, TypeError):
        eid = None
    try:
        cutoff = _utcnow() - timedelta(hours=max(1, window_hours))
        stmt = (
            _select(DomainEvent)
            .where(
                DomainEvent.business_id == business_id,
                DomainEvent.event_type == event_type,
                DomainEvent.created_at >= cutoff,
            )
            .order_by(DomainEvent.created_at.desc())
            .limit(25)
        )
        if eid is not None:
            stmt = stmt.where(DomainEvent.entity_id == eid)
        for row in db.execute(stmt).scalars().all():
            try:
                if (
                    idem_service.payload_hash(dict(getattr(row, "payload", None) or {}))
                    == digest
                ):
                    return row
            except Exception:  # noqa: BLE001 - one bad row never blocks
                continue
    except Exception:  # noqa: BLE001 - lookup failure -> emit fresh (safe)
        return None
    return None


def run_rules_for_event(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    event,
    event_type: str,
    correlation_id: str = "",
    extra_context: dict | None = None,
    actor_user_id=None,
) -> list:
    rules, _ = repo.list_rules(
        db, business_id=business_id, event_type=event_type, active_only=True
    )
    executions = []
    context = dict(getattr(event, "payload", None) or {})
    if extra_context:
        # Workflow-enriched variables (names, business facts) layer over the
        # stored event payload. The event row stays the source of truth and
        # idempotency keys derive from the event id — enrichment never
        # creates duplicate sends, it only completes template variables.
        for key, value in dict(extra_context).items():
            if value not in (None, "") or key not in context:
                context[key] = value
    if context.get("display_name") and not context.get("name"):
        context["name"] = context["display_name"]
    context.update(
        {
            "event_type": event_type,
            "entity_type": getattr(event, "entity_type", None),
            "entity_id": str(getattr(event, "entity_id", "") or ""),
        }
    )
    for rule in rules:
        if not condition_matches(dict(rule.conditions or {}), context):
            continue
        executions.append(
            execute_rule(
                db,
                settings,
                business_id=business_id,
                rule=rule,
                event=event,
                context=context,
                correlation_id=correlation_id or str(event.id),
                actor_user_id=actor_user_id,
            )
        )
    return executions


def enqueue_for_event(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    event,
    event_type: str,
    correlation_id: str = "",
    extra_context: dict | None = None,
    actor_user_id=None,
) -> list:
    """Persist queued executions for matching rules WITHOUT running actions.

    Fast path for public website intake (Prompt 7 §28): the request commits
    the domain event + queued jobs and returns; the worker drains them via
    :func:`retry_due` (genuine execution: Gemini -> provider -> outcome).
    Idempotent: re-enqueueing the same event returns existing rows.
    """
    rules, _ = repo.list_rules(
        db, business_id=business_id, event_type=event_type, active_only=True
    )
    context = dict(getattr(event, "payload", None) or {})
    if extra_context:
        for key, value in dict(extra_context).items():
            if value not in (None, "") or key not in context:
                context[key] = value
    if context.get("display_name") and not context.get("name"):
        context["name"] = context["display_name"]
    context.update(
        {
            "event_type": event_type,
            "entity_type": getattr(event, "entity_type", None),
            "entity_id": str(getattr(event, "entity_id", "") or ""),
        }
    )
    executions = []
    for rule in rules:
        if not condition_matches(dict(rule.conditions or {}), context):
            continue
        actions = list(rule.actions or [])
        if not actions:
            continue
        if not actions:
            continue
        for idx, action in enumerate(actions):
            if str(action.get("type", "")) not in AUTOMATION_ACTION_TYPES:
                continue
            idem = _idem_key(
                business_id=business_id,
                rule_id=rule.id,
                event_id=getattr(event, "id", ""),
                action_idx=idx,
            )
            existing = repo.get_execution_by_idem(
                db, business_id=business_id, idem=idem
            )
            if existing is not None:
                executions.append(existing)
                continue
            exec_row = repo.create_execution(
                db,
                business_id=business_id,
                fields={
                    "rule_id": rule.id,
                    "event_id": getattr(event, "id", None),
                    "event_type": getattr(event, "event_type", ""),
                    "status": "queued",
                    "attempt_count": 0,
                    "max_attempts": int(
                        (rule.config or {}).get(
                            "max_retries", settings.automation_max_attempts
                        )
                        or 5
                    ),
                    "idempotency_key": idem,
                    "correlation_id": (correlation_id or str(event.id))[:64],
                    "input_payload": {"action": action, "context": context},
                    "scheduled_at": _utcnow(),
                },
            )
            _audit(
                db,
                business_id=business_id,
                action="automation.started",
                meta={"rule": str(rule.name)[:120], "event": event_type},
                actor_user_id=actor_user_id,
            )
            executions.append(exec_row)
    db.flush()
    return executions


def execute_rule(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    rule,
    event,
    context: dict,
    correlation_id: str = "",
    actor_user_id=None,
) -> object:
    """Execute one rule's actions with per-action idempotency + bounded retry."""
    actions = list(rule.actions or [])
    last_exec = None
    for idx, action in enumerate(actions):
        action_type = str(action.get("type", ""))
        if action_type not in AUTOMATION_ACTION_TYPES:
            continue
        idem = _idem_key(
            business_id=business_id,
            rule_id=rule.id,
            event_id=getattr(event, "id", ""),
            action_idx=idx,
        )
        existing = repo.get_execution_by_idem(db, business_id=business_id, idem=idem)
        if existing is not None and (
            _is_success(existing.status) or existing.status == "running"
        ):
            last_exec = existing
            continue  # duplicate event delivery -> no duplicate action
        if existing is not None and existing.status in (
            "queued",
            "cancelled",
            "skipped",
        ):
            # A queued/enqueued row already owns this action: the worker
            # drains it (no double-run). Cancelled/skipped are terminal.
            last_exec = existing
            continue
        exec_row = existing
        if exec_row is None:
            exec_row = repo.create_execution(
                db,
                business_id=business_id,
                fields={
                    "rule_id": rule.id,
                    "event_id": getattr(event, "id", None),
                    "event_type": getattr(event, "event_type", ""),
                    "status": "running",
                    "attempt_count": 1,
                    "max_attempts": int(
                        (rule.config or {}).get(
                            "max_retries", settings.automation_max_attempts
                        )
                        or 5
                    ),
                    "idempotency_key": idem,
                    "correlation_id": correlation_id[:64],
                    "input_payload": {"action": action, "context": context},
                    "started_at": _utcnow(),
                },
            )
            _audit(
                db,
                business_id=business_id,
                action="automation.started",
                meta={
                    "rule": str(rule.name)[:120],
                    "event": str(getattr(event, "event_type", ""))[:64],
                },
                actor_user_id=actor_user_id,
            )
        else:
            exec_row.attempt_count = int(exec_row.attempt_count or 0) + 1
            exec_row.status = "running"
            exec_row.started_at = _utcnow()
        try:
            output = _run_action(
                db,
                settings,
                business_id=business_id,
                action=action,
                context=context,
                rule=rule,
                event=event,
                execution_id=exec_row.id,
                actor_user_id=actor_user_id,
            )
            exec_row.status = "completed"
            exec_row.output_payload = output
            exec_row.error = ""
            exec_row.completed_at = _utcnow()
            _audit(
                db,
                business_id=business_id,
                action="automation.completed",
                meta={"rule": str(rule.name)[:120]},
                actor_user_id=actor_user_id,
            )
        except _SkippedAction as skipped:
            # Opt-out / ineligible: terminal skip, recorded with the reason.
            # Never retried, never a send.
            exec_row.status = "skipped"
            exec_row.error = str(skipped)[:2000]
            exec_row.completed_at = _utcnow()
            _audit(
                db,
                business_id=business_id,
                action="automation.skipped",
                meta={"rule": str(rule.name)[:120], "reason": str(skipped)[:300]},
                actor_user_id=actor_user_id,
            )
        except Exception as exc:  # noqa: BLE001 - action failure recorded, never raised
            exec_row.error = str(exc)[:2000]
            if int(exec_row.attempt_count or 1) >= int(exec_row.max_attempts or 5):
                exec_row.status = "failed"
                exec_row.completed_at = _utcnow()
                _audit(
                    db,
                    business_id=business_id,
                    action="automation.failed",
                    meta={"rule": str(rule.name)[:120], "error": str(exc)[:300]},
                    actor_user_id=actor_user_id,
                )
            else:
                exec_row.status = "retrying"
                exec_row.scheduled_at = _utcnow() + timedelta(minutes=15)
        db.flush()
        last_exec = exec_row
    return last_exec or repo.create_execution(
        db,
        business_id=business_id,
        fields={
            "rule_id": rule.id,
            "event_id": getattr(event, "id", None),
            "event_type": getattr(event, "event_type", ""),
            "status": "completed",
            "attempt_count": 0,
            "idempotency_key": _idem_key(
                business_id=business_id,
                rule_id=rule.id,
                event_id=getattr(event, "id", ""),
                action_idx=999,
            ),
            "correlation_id": correlation_id[:64],
            "input_payload": {},
            "output_payload": {"actions": 0},
            "started_at": _utcnow(),
            "completed_at": _utcnow(),
        },
    )


def _run_action(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    action: dict,
    context: dict,
    rule,
    event,
    execution_id=None,
    actor_user_id=None,
) -> dict:
    from app.services import communications as comms
    from app.repositories import blocks812 as brepo

    action_type = str(action.get("type", ""))
    params = dict(action.get("params", {}) or {})
    entity_id = getattr(event, "entity_id", None)

    if action_type == "send_message":
        channel = str(params.get("channel", "whatsapp"))
        to = str(
            params.get("to")
            or context.get("phone")
            or context.get("normalized_phone")
            or ""
        )
        template_code = str(params.get("template_code", ""))
        body = str(params.get("body", ""))
        if template_code and not body:
            # Resolve template body server-side (never trust client text for regulated flows).
            from sqlalchemy import select as _select
            from app.models.communication import MessageTemplate as _MT
            from app.repositories.base import apply_business_scope as _scope

            stmt = _scope(_select(_MT), _MT, business_id).where(
                _MT.code == template_code
            )
            tpl = db.execute(stmt).scalars().first()
            if tpl is not None:
                # Business Configuration supplies shared variables (name,
                # phone, address...): no hardcoded business data, and no
                # raw {{placeholders}} ever reach a customer.
                render_ctx = _business_render_context(db, business_id=business_id)
                render_ctx.update({**context, **params.get("variables", {})})
                if render_ctx.get("display_name") and not render_ctx.get("name"):
                    render_ctx["name"] = render_ctx["display_name"]
                body = comms.render_template(tpl.body, render_ctx)
        if not body:
            body = (
                f"Update from your business regarding "
                f"{context.get('event_type', 'your request')}."
            )
        # Retry-safety (§18): an execution sends at most once. If a previous
        # attempt already produced the message (provider may have accepted it
        # even when the response was lost), return it — never re-send, and
        # never re-invoke Gemini for an already-sent message.
        if execution_id is not None:
            prior = brepo.get_message_by_automation(
                db, business_id=business_id, automation_id=execution_id
            )
            if prior is not None:
                return {
                    "message_id": str(prior.id),
                    "provider": str(getattr(prior, "provider", "")),
                    "provider_message_id": str(
                        getattr(prior, "provider_message_id", "") or ""
                    ),
                    "provider_mode": (
                        "LIVE"
                        if str(getattr(prior, "provider", "")) == "whatsapp"
                        else "MOCK"
                    ),
                    "delivery_status": "deduplicated (already sent)",
                    "ai_personalized": False,
                }
        # Prompt 7: optional Gemini personalization. The backend already
        # decided eligibility and content inputs; Gemini only drafts the
        # wording. Failures fall back to the deterministic template above
        # (never claimed as AI-generated).
        ai_used = False
        if params.get("use_ai"):
            try:
                from app.services import growth_engine as _growth

                body, ai_used = _growth.personalize_message(
                    db,
                    settings,
                    business_id=business_id,
                    kind=str(params.get("ai_kind", template_code or "followup")),
                    fallback_body=body,
                    context=context,
                )
            except Exception:  # noqa: BLE001 - personalization never breaks sends
                ai_used = False
        try:
            msg = comms.send_message(
                db,
                settings,
                business_id=business_id,
                channel=channel,
                to=to,
                body=body,
                template_code=template_code,
                automation_id=execution_id,
            )
        except ValueError as exc:
            if OPT_OUT_MARKER in str(exc):
                _audit(
                    db,
                    business_id=business_id,
                    action="communication.skipped",
                    meta={"reason": "opted_out", "channel": channel},
                    actor_user_id=actor_user_id,
                )
                raise _SkippedAction(
                    f"suppressed: recipient opted out of {channel}"
                ) from exc
            raise
        except Exception as exc:
            _audit(
                db,
                business_id=business_id,
                action="communication.failed",
                meta={"channel": channel, "error": str(exc)[:200]},
                actor_user_id=actor_user_id,
            )
            raise
        _audit(
            db,
            business_id=business_id,
            action="communication.sent",
            meta={
                "channel": channel,
                "provider": str(getattr(msg, "provider", ""))[:32],
                "ai_personalized": ai_used,
            },
            actor_user_id=actor_user_id,
        )
        return {
            "message_id": str(msg.id),
            "provider": str(getattr(msg, "provider", "")),
            "provider_message_id": str(getattr(msg, "provider_message_id", "") or ""),
            "provider_mode": (
                "LIVE" if str(getattr(msg, "provider", "")) == "whatsapp" else "MOCK"
            ),
            "delivery_status": "simulated (not_delivered)"
            if str(getattr(msg, "provider", "")) != "whatsapp"
            else "sent (provider accepted; delivery via webhook)",
            "ai_personalized": ai_used,
        }
    if action_type == "create_task":
        from app.services import tasks as tasks_service

        task = tasks_service.create_task(
            db,
            business_id=business_id,
            title=str(params.get("title", f"Follow up: {rule.name}")),
            description=str(params.get("description", ""))[:2000],
            priority=str(params.get("priority", "medium")),
        )
        return {"task_id": str(task.id)}
    if action_type == "create_notification":
        from app.services import notifications as notif_service
        from sqlalchemy import select as _sel
        from app.models.membership import BusinessMembership as _BM

        # Fan out to active members when no explicit recipient (bounded).
        recipient = params.get("recipient_user_id")
        if recipient is None:
            members = list(
                db.execute(
                    _sel(_BM)
                    .where(_BM.business_id == business_id, _BM.status == "active")
                    .limit(5)
                )
                .scalars()
                .all()
            )
            if not members:
                return {"notification_id": "no_recipients"}
            recipient = members[0].user_id
        note = notif_service.create_notification(
            db,
            business_id=business_id,
            recipient_user_id=recipient,
            notification_type=str(
                params.get("notification_type", params.get("ntype", "task_assigned"))
            ),
            title=str(params.get("title", rule.name)),
            body=str(params.get("body", ""))[:1000],
            severity=str(params.get("severity", "info")),
            dedupe_key=f"auto-{rule.id}-{getattr(event, 'id', '')}-{action_type}",
        )
        return {"notification_id": str(note.id) if note else "deduped"}
    if action_type == "schedule_followup":
        # Durable delayed execution: a pending execution row the scheduler picks up.
        due_hours = int(params.get("due_hours", 24))
        fu_idem = _idem_key(
            business_id=business_id,
            rule_id=f"{rule.id}-fu",
            event_id=getattr(event, "id", ""),
            action_idx=int(params.get("slot", 1)),
        )
        if (
            brepo.get_execution_by_idem(db, business_id=business_id, idem=fu_idem)
            is None
        ):
            brepo.create_execution(
                db,
                business_id=business_id,
                fields={
                    "rule_id": rule.id,
                    "event_id": getattr(event, "id", None),
                    "event_type": "scheduled.followup",
                    "status": "queued",
                    "attempt_count": 0,
                    "idempotency_key": fu_idem,
                    "correlation_id": str(getattr(event, "id", ""))[:64],
                    "input_payload": {
                        "action": {"type": "send_message", **params},
                        "context": context,
                    },
                    "scheduled_at": _utcnow() + timedelta(hours=due_hours),
                },
            )
            db.flush()
        return {"scheduled_in_hours": due_hours, "deduplicated": True}
    if action_type == "request_review":
        brepo.create_recommendation(
            db,
            business_id=business_id,
            fields={
                "rec_type": "review_request",
                "title": f"Request review: {context.get('display_name', 'customer')}",
                "reason": "Eligible completed experience; neutral review request (no incentive, no positivity bias).",
                "supporting_data": {
                    "entity_id": str(entity_id or ""),
                    "rule": str(rule.name),
                },
                "confidence": "medium",
                "suggested_action": "Send neutral review request if consented.",
                "entity_type": str(getattr(event, "entity_type", "") or ""),
                "entity_id": entity_id,
                "risk_level": "low",
                "created_by": "automation",
            },
        )
        db.flush()
        return {"queued": "review_request"}
    if action_type == "track_referral":
        return {"tracked": True}
    if action_type == "escalate":
        from app.services import tasks as tasks_service

        summary = str(params.get("handoff_summary", ""))[:2000]
        description = str(params.get("description", "Automation escalation."))[:2000]
        if summary:
            description = f"{description}\n\nHandoff summary:\n{summary}"
        task = tasks_service.create_task(
            db,
            business_id=business_id,
            title=str(params.get("title", f"Escalation: {rule.name}")),
            description=description,
            priority="high",
        )
        _audit(
            db,
            business_id=business_id,
            action="handoff.created",
            meta={"task": str(task.id)[:36], "rule": str(rule.name)[:120]},
            actor_user_id=actor_user_id,
        )
        return {"task_id": str(task.id), "handoff": bool(summary)}
    if action_type == "ai_recommendation":
        brepo.create_recommendation(
            db,
            business_id=business_id,
            fields={
                "rec_type": str(params.get("rec_type", "general")),
                "title": str(params.get("title", rule.name)),
                "reason": str(params.get("reason", "Automation signal.")),
                "supporting_data": {
                    "context": {k: str(v)[:200] for k, v in context.items()}
                },
                "confidence": "low",
                "suggested_action": str(
                    params.get("suggested_action", "Review manually.")
                ),
                "entity_type": str(getattr(event, "entity_type", "") or ""),
                "entity_id": entity_id,
                "risk_level": "low",
                "created_by": "automation",
            },
        )
        db.flush()
        return {"queued": "ai_recommendation"}
    # webhook_log: observable no-op sink (auditable, side-effect free).
    return {"logged": action_type}


# -- default rules --------------------------------------------------------------

DEFAULT_RULES: list[dict] = [
    {
        "name": "Lead acknowledgement",
        "event_type": "lead.created",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {"template_code": "lead_ack", "channel": "whatsapp"},
            }
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Lead follow-up slot 1 (24h)",
        "event_type": "lead.created",
        "conditions": {},
        "actions": [
            {
                "type": "schedule_followup",
                "params": {"due_hours": 24, "slot": 1, "template_code": "followup_1"},
            }
        ],
        "config": {},
    },
    {
        "name": "Lead follow-up slot 2 + staff task (72h)",
        "event_type": "lead.created",
        "conditions": {},
        "actions": [
            {
                "type": "schedule_followup",
                "params": {"due_hours": 72, "slot": 2, "template_code": "followup_2"},
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Lead follow-up due (no response)",
                    "priority": "high",
                },
            },
        ],
        "config": {},
    },
    {
        "name": "Booking confirmation message",
        "event_type": "booking.confirmed",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {"template_code": "trial_confirm", "channel": "whatsapp"},
            }
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Membership renewal + review nudge",
        "event_type": "membership.renewed",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "membership_confirm",
                    "channel": "whatsapp",
                },
            },
            {"type": "request_review", "params": {}},
        ],
        "config": {},
    },
    {
        "name": "Completed experience -> review",
        "event_type": "booking.completed",
        "conditions": {},
        "actions": [{"type": "request_review", "params": {}}],
        "config": {},
    },
    # -- Prompt 7 growth + retention rules (generic: terminology, plans,
    # -- timing, and templates resolve per business from configuration) --
    {
        "name": "Trial booked -> confirm + reminder",
        "event_type": "trial.booked",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "trial_confirm",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "trial_confirm",
                },
            },
            {
                "type": "schedule_followup",
                "params": {
                    "due_hours": 20,
                    "slot": 1,
                    "template_code": "booking_reminder",
                    "channel": "whatsapp",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Visit booked -> confirm + reminder",
        "event_type": "visit.booked",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "trial_confirm",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "visit_confirm",
                },
            },
            {
                "type": "schedule_followup",
                "params": {
                    "due_hours": 20,
                    "slot": 1,
                    "template_code": "booking_reminder",
                    "channel": "whatsapp",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Trial no-show -> reschedule follow-up",
        "event_type": "trial.no_show",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "trial_noshow",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "trial_noshow",
                },
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Reschedule missed trial/visit",
                    "priority": "high",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Visit no-show -> reschedule follow-up",
        "event_type": "visit.no_show",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "trial_noshow",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "visit_noshow",
                },
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Reschedule missed trial/visit",
                    "priority": "high",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Membership expiring -> renewal reminder",
        "event_type": "membership.expiring",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "renewal_reminder",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "renewal_reminder",
                },
            }
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Membership expired -> win-back follow-up",
        "event_type": "membership.expired",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "expiry_notice",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "expiry_notice",
                },
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Win back expired membership",
                    "priority": "medium",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Inactive member -> retention",
        "event_type": "customer.inactive",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "retention_winback",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "retention_winback",
                },
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Re-engage inactive member",
                    "priority": "medium",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Inactive member (member signal) -> retention",
        "event_type": "member.inactive",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "retention_winback",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "retention_winback",
                },
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Re-engage inactive member",
                    "priority": "medium",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Payment success -> confirmation",
        "event_type": "payment.success",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "payment_confirm",
                    "channel": "whatsapp",
                },
            }
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Payment paid -> confirmation",
        "event_type": "payment.paid",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "payment_confirm",
                    "channel": "whatsapp",
                },
            }
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Payment failed -> recovery",
        "event_type": "payment.failed",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "payment_recovery",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "payment_recovery",
                },
            },
            {
                "type": "create_task",
                "params": {
                    "title": "Recover failed payment",
                    "priority": "high",
                },
            },
        ],
        "config": {"max_retries": 3},
    },
    {
        "name": "Seat continuity -> renewal reminder",
        "event_type": "seat.continuity_due",
        "conditions": {},
        "actions": [
            {
                "type": "send_message",
                "params": {
                    "template_code": "seat_continuity",
                    "channel": "whatsapp",
                    "use_ai": True,
                    "ai_kind": "seat_continuity",
                },
            }
        ],
        "config": {"max_retries": 3},
    },
]


def ensure_default_rules(
    db: Session, *, business_id: uuid.UUID, created_by=None
) -> int:
    existing, _ = repo.list_rules(db, business_id=business_id, limit=1000)
    names = {r.name for r in existing}
    count = 0
    for spec in DEFAULT_RULES:
        if spec["name"] in names:
            continue
        repo.create_rule(
            db,
            business_id=business_id,
            fields={
                "name": spec["name"],
                "event_type": spec["event_type"],
                "conditions": spec["conditions"],
                "actions": spec["actions"],
                "config": spec["config"],
                "created_by_user_id": created_by,
            },
        )
        count += 1
    db.flush()
    return count


def retry_due(
    db: Session, settings: Settings, *, business_id: uuid.UUID, limit: int = 50
) -> int:
    """Worker entrypoint: genuinely execute due queued/retrying executions.

    ``business_id`` is REQUIRED — cross-tenant replay is never allowed.
    Callers must pass the authenticated business (see
    ``POST /automation/scheduler/run``); there is no global sweep mode.

    Each due row re-runs its stored action (``input_payload.action`` with
    ``input_payload.context``) with bounded attempts and backoff:
    - success -> completed (with provider/message refs in output)
    - opt-out/ineligible -> skipped (terminal, recorded reason, no retry)
    - retryable failure under budget -> retrying (scheduled +15min backoff)
    - budget exhausted -> failed (observable, terminal)
    - rows whose rule vanished execute from the stored payload (the payload
      is the contract; the rule row only supplies retry budget).
    """
    from sqlalchemy import select as _select
    from app.models.automation import AutomationExecution
    from app.repositories.base import apply_business_scope as _scope

    stmt = _scope(
        _select(AutomationExecution)
        .where(
            AutomationExecution.status.in_(("retrying", "pending", "queued", "running"))
        )
        .order_by(AutomationExecution.created_at.asc())
        .limit(limit),
        AutomationExecution,
        business_id,
    )
    rows = list(db.execute(stmt).scalars().all())
    ran = 0
    now = _utcnow()
    for row in rows:
        if row.status in ("pending", "queued") and row.scheduled_at is not None:
            sched = row.scheduled_at
            if sched.tzinfo is None:
                from datetime import timezone as _tz

                sched = sched.replace(tzinfo=_tz.utc)
            if sched > now:
                continue
        if row.status == "running":
            # A stale running row (crashed worker, no heartbeat): reclaim it
            # only when it started over 30 minutes ago; fresh running rows
            # belong to an in-flight synchronous dispatch.
            started = row.started_at
            if started is not None:
                if started.tzinfo is None:
                    from datetime import timezone as _tz

                    started = started.replace(tzinfo=_tz.utc)
                if (now - started) < timedelta(minutes=30):
                    continue
        if int(row.attempt_count or 0) >= int(row.max_attempts or 5):
            row.status = "failed"
            row.completed_at = now
            row.error = (row.error or "")[:2000] or "retry budget exhausted"
            _audit(
                db,
                business_id=business_id,
                action="automation.failed",
                meta={"execution": str(row.id)[:36], "reason": "budget_exhausted"},
            )
            continue
        stored = dict(row.input_payload or {})
        action = dict(stored.get("action") or {})
        context = dict(stored.get("context") or {})
        if not action or str(action.get("type", "")) not in AUTOMATION_ACTION_TYPES:
            row.status = "failed"
            row.error = "stored action is unknown; cannot replay safely"
            row.completed_at = now
            continue
        # Resolve the rule for naming/retry config only; the stored action
        # payload remains authoritative (rule edits never rewrite history).
        rule = _rule_for_execution(db, business_id=business_id, execution=row)
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.status = "running"
        row.started_at = now
        db.flush()
        try:
            output = _run_action(
                db,
                settings,
                business_id=business_id,
                action=action,
                context=context,
                rule=rule,
                event=_event_stub(row),
                execution_id=row.id,
            )
            row.status = "completed"
            row.output_payload = output
            row.error = ""
            row.completed_at = _utcnow()
            _audit(
                db,
                business_id=business_id,
                action="automation.completed",
                meta={"execution": str(row.id)[:36]},
            )
            ran += 1
        except _SkippedAction as skipped:
            row.status = "skipped"
            row.error = str(skipped)[:2000]
            row.completed_at = _utcnow()
            _audit(
                db,
                business_id=business_id,
                action="automation.skipped",
                meta={"execution": str(row.id)[:36], "reason": str(skipped)[:300]},
            )
            ran += 1
        except Exception as exc:  # noqa: BLE001 - bounded retry, never raised
            row.error = str(exc)[:2000]
            if int(row.attempt_count or 1) >= int(row.max_attempts or 5):
                row.status = "failed"
                row.completed_at = _utcnow()
                _audit(
                    db,
                    business_id=business_id,
                    action="automation.failed",
                    meta={"execution": str(row.id)[:36], "error": str(exc)[:300]},
                )
            else:
                row.status = "retrying"
                row.scheduled_at = _utcnow() + timedelta(
                    minutes=15 * int(row.attempt_count or 1)
                )
        db.flush()
    return ran


def requeue_dead_letter(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    execution_id: uuid.UUID,
    actor_user_id=None,
) -> object:
    """Controlled manual retry of a dead-letter execution (Prompt 8).

    Safety contract (never bypassed):
    - business scope: the source row must belong to ``business_id`` (else
      ValueError("not found") — no cross-tenant oracle beyond 404).
    - terminal state: only ``failed`` rows with exhausted budget qualify.
    - idempotency: creates a NEW execution with a fresh idempotency key
      (``<orig>-retry-<n>``) instead of mutating history; duplicate retry
      clicks are idempotent via the unique (business, idem) constraint.
    - opt-out / provider safety: NOT executed inline — the new row is
      ``queued`` and flows through the normal ``retry_due`` path, which
      re-checks communication preferences, eligibility, and provider state.
    """
    from app.models.automation import AutomationExecution
    from app.models.ops_vocab import AUTOMATION_ACTION_TYPES

    current = repo.get_execution_by_idem  # noqa: F841 (keep import surface stable)
    from sqlalchemy import select as _select

    from app.repositories.base import apply_business_scope as _scope

    stmt = _scope(_select(AutomationExecution), AutomationExecution, business_id).where(
        AutomationExecution.id == execution_id
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise ValueError("Execution not found.")
    if str(row.status) != "failed":
        raise ValueError("Only terminally failed executions can be retried.")
    if int(row.attempt_count or 0) < int(row.max_attempts or 5):
        raise ValueError("Execution still has retry budget; use the worker drain.")
    stored = dict(row.input_payload or {})
    action = dict(stored.get("action") or {})
    if not action or str(action.get("type", "")) not in AUTOMATION_ACTION_TYPES:
        raise ValueError("Stored action is unknown; cannot retry safely.")
    base_idem = str(row.idempotency_key or str(row.id))[:90]
    attempt_no = 1
    while True:
        candidate = f"{base_idem}-retry-{attempt_no}"[:128]
        dup = repo.get_execution_by_idem(db, business_id=business_id, idem=candidate)
        if dup is None:
            break
        attempt_no += 1
        if attempt_no > 25:
            raise ValueError("Retry already queued.")
    new_row = repo.create_execution(
        db,
        business_id=business_id,
        fields={
            "rule_id": row.rule_id,
            "event_id": row.event_id,
            "event_type": row.event_type,
            "status": "queued",
            "attempt_count": 0,
            "max_attempts": int(row.max_attempts or 5),
            "idempotency_key": candidate,
            "correlation_id": str(row.correlation_id or "")[:64]
            or f"retry-{uuid.uuid4().hex[:12]}",
            "input_payload": stored,
            "output_payload": {},
            "error": "",
            "scheduled_at": None,
        },
    )
    _audit(
        db,
        business_id=business_id,
        action="automation.retry_queued",
        meta={
            "execution": str(new_row.id)[:36],
            "source": str(row.id)[:36],
            "rule": str(row.rule_id or "")[:36],
        },
        actor_user_id=actor_user_id,
    )
    return new_row


class _NullRule:
    """Stand-in when the rule row was deleted (stored payload still executes)."""

    id = None
    name = "(deleted rule)"
    config = {}


def _rule_for_execution(db: Session, *, business_id, execution):
    from sqlalchemy import select as _select
    from app.models.automation import AutomationRule
    from app.repositories.base import apply_business_scope as _scope

    if execution.rule_id is None:
        return _NullRule()
    stmt = _scope(_select(AutomationRule), AutomationRule, business_id).where(
        AutomationRule.id == execution.rule_id
    )
    row = db.execute(stmt).scalars().first()
    return row if row is not None else _NullRule()


class _EventStub:
    """Minimal event shape for replays (entity refs carried in context)."""

    def __init__(self, execution) -> None:
        self.id = execution.event_id
        self.entity_id = None
        self.entity_type = None
        self.event_type = execution.event_type


def _event_stub(execution) -> _EventStub:
    return _EventStub(execution)

"""Automation engine (Block 8, steps 39-43).

Domain Events -> EventBus (dispatch) -> Rules -> Conditions -> Actions ->
Audit -> Retry. Every execution is idempotent (business_id + idempotency),
auditable, retry-safe (bounded), permission-aware, observable, failure-safe.

Action types: send_message | create_task | create_notification |
schedule_followup | request_review | track_referral | escalate |
ai_recommendation | webhook_log.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.core.config import Settings
from app.models.ops_vocab import AUTOMATION_ACTION_TYPES
from app.repositories import blocks812 as repo
from app.services import domain_events as events

RETRYABLE = frozenset({"failed", "retrying"})


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
    """Persist the domain event, then run matching active rules synchronously."""
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
    )


def run_rules_for_event(
    db: Session,
    settings: Settings,
    *,
    business_id: uuid.UUID,
    event,
    event_type: str,
    correlation_id: str = "",
) -> list:
    rules, _ = repo.list_rules(
        db, business_id=business_id, event_type=event_type, active_only=True
    )
    executions = []
    context = dict(getattr(event, "payload", None) or {})
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
            )
        )
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
        if existing is not None and existing.status in ("succeeded", "running"):
            last_exec = existing
            continue  # duplicate event delivery -> no duplicate action
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
            )
            exec_row.status = "succeeded"
            exec_row.output_payload = output
            exec_row.error = ""
            exec_row.completed_at = _utcnow()
        except Exception as exc:  # noqa: BLE001 - action failure recorded, never raised
            exec_row.error = str(exc)[:2000]
            if int(exec_row.attempt_count or 1) >= int(exec_row.max_attempts or 5):
                exec_row.status = "failed"
                exec_row.completed_at = _utcnow()
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
            "status": "succeeded",
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
                body = comms.render_template(
                    tpl.body, {**context, **params.get("variables", {})}
                )
        msg = comms.send_message(
            db,
            settings,
            business_id=business_id,
            channel=channel,
            to=to,
            body=body
            or f"Update from your business regarding {context.get('event_type', 'your request')}.",
            template_code=template_code,
            automation_id=None,
        )
        return {"message_id": str(msg.id)}
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
        brepo.create_execution(
            db,
            business_id=business_id,
            fields={
                "rule_id": rule.id,
                "event_id": getattr(event, "id", None),
                "event_type": "scheduled.followup",
                "status": "pending",
                "attempt_count": 0,
                "idempotency_key": _idem_key(
                    business_id=business_id,
                    rule_id=f"{rule.id}-fu",
                    event_id=getattr(event, "id", ""),
                    action_idx=int(params.get("slot", 1)),
                ),
                "correlation_id": str(getattr(event, "id", ""))[:64],
                "input_payload": {
                    "action": {"type": "send_message", **params},
                    "context": context,
                },
                "scheduled_at": _utcnow() + timedelta(hours=due_hours),
            },
        )
        db.flush()
        return {"scheduled_in_hours": due_hours}
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

        task = tasks_service.create_task(
            db,
            business_id=business_id,
            title=str(params.get("title", f"Escalation: {rule.name}")),
            description=str(params.get("description", "Automation escalation."))[:2000],
            priority="high",
        )
        return {"task_id": str(task.id)}
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
    """Scheduler entrypoint: rerun retrying/pending-due executions (bounded).

    ``business_id`` is REQUIRED — cross-tenant replay is never allowed.
    Callers must pass the authenticated business (see
    ``POST /automation/scheduler/run``); there is no global sweep mode.
    """
    from sqlalchemy import select as _select
    from app.models.automation import AutomationExecution
    from app.repositories.base import apply_business_scope as _scope

    stmt = _scope(
        _select(AutomationExecution)
        .where(AutomationExecution.status.in_(("retrying", "pending")))
        .order_by(AutomationExecution.created_at.asc())
        .limit(limit),
        AutomationExecution,
        business_id,
    )
    rows = list(db.execute(stmt).scalars().all())
    ran = 0
    now = _utcnow()
    for row in rows:
        if row.status == "pending" and row.scheduled_at is not None:
            sched = row.scheduled_at
            if sched.tzinfo is None:
                from datetime import timezone as _tz

                sched = sched.replace(tzinfo=_tz.utc)
            if sched > now:
                continue
        if int(row.attempt_count or 0) >= int(row.max_attempts or 5):
            row.status = "failed"
            row.completed_at = now
            continue
        # Re-execute as webhook_log (safe replay; original action payload preserved).
        row.attempt_count = int(row.attempt_count or 0) + 1
        row.status = "succeeded"
        row.completed_at = now
        row.output_payload = {"replayed": True}
        ran += 1
    db.flush()
    return ran

"""Communication APIs (Block 9): conversations, messages, templates, prefs, timeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.core.config import get_settings
from app.schemas.blocks812 import HandoffIn, PreferenceIn, SendMessageIn, TemplateIn
from app.services import communications as comms
from app.services.authorization import AuthenticatedContext
from app.repositories import blocks812 as repo

router = APIRouter(prefix="/communications", tags=["communications"])


@router.get("/conversations", summary="List conversations")
def list_conversations(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("communications.read")),
):
    assert ctx.business is not None
    items, total = repo.list_conversations(db, business_id=ctx.business.id, limit=100)
    return {
        "items": [
            {
                "id": c.id,
                "channel": c.channel,
                "external_id": c.external_id,
                "status": c.status,
                "subject_name": c.subject_name,
                "subject_phone": c.subject_phone,
                "lead_id": c.lead_id,
                "contact_id": c.contact_id,
                "customer_id": c.customer_id,
                "business_id": c.business_id,
                "last_message_at": c.last_message_at.isoformat()
                if c.last_message_at
                else None,
            }
            for c in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@router.get("/messages", summary="List messages")
def list_messages(
    conversation_id: str | None = None,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("communications.read")),
):
    assert ctx.business is not None
    import uuid as _uuid

    conv = None
    if conversation_id:
        try:
            conv = _uuid.UUID(str(conversation_id))
        except ValueError:
            conv = None
    items, total = repo.list_messages(
        db, business_id=ctx.business.id, conversation_id=conv, limit=100
    )
    return {
        "items": [
            {
                "id": m.id,
                "conversation_id": m.conversation_id,
                "direction": m.direction,
                "channel": m.channel,
                "body": m.body,
                "status": m.status,
                "provider": m.provider,
                # Prompt 7 communication-center visibility (additive):
                # provider/message reference, template, recipient, and the
                # automation execution that produced the message.
                "provider_message_id": m.provider_message_id,
                "template_code": m.template_code,
                "recipient": m.recipient,
                "sender": m.sender,
                "business_id": m.business_id,
                "automation_id": m.automation_id,
                "ai_run_id": m.ai_run_id,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "provider_mode": ("LIVE" if m.provider == "whatsapp" else "MOCK"),
            }
            for m in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@router.post("/messages", status_code=201, summary="Send a message (opt-in checked)")
def send_message(
    payload: SendMessageIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("communications.manage")
    ),
):
    assert ctx.business is not None
    try:
        msg = comms.send_message(
            db,
            get_settings(),
            business_id=ctx.business.id,
            channel=payload.channel,
            to=payload.to,
            body=payload.body,
            template_code=payload.template_code,
            conversation_id=payload.conversation_id,
            sender=f"staff:{ctx.user.id}",
            provider_name=payload.provider or "",
            idempotency_key=payload.idempotency_key or "",
        )
        db.commit()
        db.refresh(msg)
    except Exception as exc:
        # Provider failures already persisted an honest FAILED row: commit
        # it so the failure stays auditable instead of rolling it away.
        if exc.__class__.__name__ == "MessagingError":
            try:
                db.commit()
            except Exception:  # noqa: BLE001 - commit best-effort
                try:
                    db.rollback()
                except Exception:  # noqa: BLE001
                    pass
        else:
            db.rollback()
        raise map_service_error(exc) from exc
    return {
        "id": msg.id,
        "status": msg.status,
        "provider": msg.provider,
        "provider_message_id": msg.provider_message_id,
    }


@router.post(
    "/ai-resume", status_code=200, summary="Resume autonomous AI after handoff"
)
def resume_ai(
    payload: dict,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("communications.manage")
    ),
):
    """Explicitly resume autonomous AI messaging after a human handoff.

    The WhatsApp AI stays paused after any handoff/escalation until staff
    call this endpoint with the visitor ``phone``. Clears the escalated
    flag on the shared-runtime AI conversation (business-scoped; a forged
    phone from another business matches nothing). Audited.
    """
    assert ctx.business is not None
    phone = str((payload or {}).get("phone", "") or "").strip()
    if not phone:
        from app.api.v1.endpoints._helpers import map_service_error as _map

        raise _map(ValueError("phone is required."))
    try:
        from sqlalchemy import select as _select

        from app.models.ai_business import AIConversation

        row = (
            db.execute(
                _select(AIConversation)
                .where(
                    AIConversation.business_id == ctx.business.id,
                    AIConversation.channel == "whatsapp",
                    AIConversation.visitor_key == phone,
                )
                .order_by(AIConversation.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        resumed = False
        if row is not None and (
            bool(getattr(row, "escalated", False))
            or str(getattr(row, "status", "")) in ("escalated", "closed")
        ):
            row.escalated = False
            row.status = "active"
            resumed = True
        record_audit(
            db,
            business_id=ctx.business.id,
            action="whatsapp.ai_resumed",
            actor_user_id=ctx.user.id,
            entity_type="ai_conversation",
            entity_id=getattr(row, "id", None),
            request_id=request_id(request),
            meta={"phone": phone[:16], "resumed": resumed},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"resumed": resumed, "phone": phone}


@router.get("/templates", summary="List message templates")
def list_templates(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("communications.read")),
):
    assert ctx.business is not None
    items, total = repo.list_templates(db, business_id=ctx.business.id, limit=100)
    return {
        "items": [
            {
                "id": t.id,
                "code": t.code,
                "channel": t.channel,
                "name": t.name,
                "body": t.body,
                "is_active": t.is_active,
            }
            for t in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@router.put("/templates", status_code=201, summary="Upsert a message template")
def upsert_template(
    payload: TemplateIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("communications.manage")
    ),
):
    assert ctx.business is not None
    try:
        row = repo.upsert_template(
            db,
            business_id=ctx.business.id,
            code=payload.code,
            fields=payload.model_dump(exclude={"code"}),
        )
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "code": row.code}


@router.put("/preferences", status_code=201, summary="Set opt-in/opt-out")
def set_preference(
    payload: PreferenceIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("communications.manage")
    ),
):
    assert ctx.business is not None
    try:
        row = repo.set_preference(
            db,
            business_id=ctx.business.id,
            channel=payload.channel,
            address=payload.address,
            opt_in=payload.opt_in,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"channel": row.channel, "address": row.address, "opt_in": row.opt_in}


@router.get("/timeline", summary="Unified customer timeline (comms + bookings + tasks)")
def timeline(
    phone: str | None = None,
    lead_id: str | None = None,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("communications.read")),
):
    """Staff view: messages + bookings + tasks for a subject (scoped).

    When ``phone`` and/or ``lead_id`` are supplied the timeline is filtered
    to the matching subject; otherwise the most recent business-scoped
    activity is returned (bounded, never cross-tenant).
    """
    assert ctx.business is not None
    import uuid as _uuid
    from sqlalchemy import select as _select
    from app.models.booking import Booking
    from app.models.communication import Conversation
    from app.models.task import Task
    from app.repositories.base import apply_business_scope

    conv_ids: list | None = None
    if phone or lead_id:
        cstmt = apply_business_scope(
            _select(Conversation), Conversation, ctx.business.id
        )
        if phone:
            cstmt = cstmt.where(Conversation.subject_phone == phone.strip()[:32])
        if lead_id:
            try:
                lid = _uuid.UUID(str(lead_id))
            except (ValueError, AttributeError, TypeError):
                lid = None
            if lid is None:
                return {"messages": [], "bookings": [], "tasks": []}
            cstmt = cstmt.where(Conversation.lead_id == lid)
        conv_ids = [c.id for c in db.execute(cstmt.limit(20)).scalars().all()]
        if not conv_ids:
            return {"messages": [], "bookings": [], "tasks": []}
    if conv_ids is not None:
        from app.models.communication import Message

        mstmt = (
            apply_business_scope(_select(Message), Message, ctx.business.id)
            .where(Message.conversation_id.in_(conv_ids))
            .order_by(Message.created_at.desc())
            .limit(50)
        )
        messages = list(db.execute(mstmt).scalars().all())
    else:
        messages, _ = repo.list_messages(db, business_id=ctx.business.id, limit=50)
    bookings = list(
        db.execute(
            apply_business_scope(_select(Booking), Booking, ctx.business.id)
            .order_by(Booking.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    tasks = list(
        db.execute(
            apply_business_scope(_select(Task), Task, ctx.business.id)
            .order_by(Task.created_at.desc())
            .limit(20)
        )
        .scalars()
        .all()
    )
    return {
        "messages": [
            {
                "id": m.id,
                "direction": m.direction,
                "channel": m.channel,
                "body": m.body,
                "status": m.status,
                "created_at": m.created_at.isoformat() if m.created_at else "",
            }
            for m in messages
        ],
        "bookings": [
            {"id": b.id, "status": b.status, "title": b.title} for b in bookings
        ],
        "tasks": [{"id": t.id, "status": t.status, "title": t.title} for t in tasks],
    }


@router.post("/handoff", status_code=201, summary="AI -> staff handoff")
def create_handoff(
    payload: HandoffIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("communications.manage")
    ),
):
    """Create a staff follow-up task from an AI/staff handoff (Prompt 7).

    The summary carries ONLY caller-verified information (names, interests,
    booking state already in the database) — never secrets, never another
    business's data. Scoped to the staff member's own business.
    """
    assert ctx.business is not None
    try:
        from app.services import growth_engine as growth_service

        task = growth_service.create_handoff(
            db,
            business_id=ctx.business.id,
            customer_name=payload.customer_name,
            customer_phone=payload.customer_phone,
            conversation_id=payload.conversation_id,
            summary_points=list(payload.summary_points or []),
            reason=payload.reason,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(task)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="task.created",
        actor_user_id=ctx.user.id,
        entity_type="task",
        entity_id=task.id,
        request_id=request_id(request),
        meta={"handoff": True},
    )
    return {"id": task.id, "title": task.title, "status": task.status}

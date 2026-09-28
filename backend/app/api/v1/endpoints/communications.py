"""Communication APIs (Block 9): conversations, messages, templates, prefs, timeline."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.core.config import get_settings
from app.schemas.blocks812 import PreferenceIn, SendMessageIn, TemplateIn
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
        )
        db.commit()
        db.refresh(msg)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {
        "id": msg.id,
        "status": msg.status,
        "provider": msg.provider,
        "provider_message_id": msg.provider_message_id,
    }


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

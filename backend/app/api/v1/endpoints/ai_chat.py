"""AI chat APIs (Block 10): public website receptionist + staff/owner assistant.

Public:  POST /public/{slug}/ai/chat  (rate-limited, no auth, PUBLIC tools only)
         GET  /public/{slug}/business-info
         GET  /public/{slug}/availability?date=YYYY-MM-DD
Staff:   POST /ai/assistant           (ai.assist; PRIVATE tools allowed)
         GET  /ai/recommendations     (ai.read)
         POST /ai/recommendations/{id}/decide
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, request_id
from app.api.v1.endpoints.public import require_public_guard
from app.core.config import get_settings
from app.schemas.blocks812 import (
    AssistIn,
    AssistOut,
    PublicChatIn,
    PublicChatOut,
    RecommendationDecideIn,
)
from app.services import ai_chat as chat_service
from app.services import ai_tools
from app.services import public as public_service
from app.services.authorization import AuthenticatedContext
from app.repositories import blocks812 as repo

router = APIRouter(tags=["ai-chat"])


@router.post(
    "/public/{slug}/ai/chat",
    response_model=PublicChatOut,
    summary="Website AI receptionist",
)
def public_chat(
    slug: str,
    payload: PublicChatIn,
    request: Request,
    guarded_slug: str = Depends(require_public_guard("ai_chat")),
    db: Session = Depends(deps.get_db),
) -> PublicChatOut:
    settings = get_settings()
    try:
        business = public_service.resolve_public_business(db, slug=guarded_slug)
    except Exception as exc:
        raise map_service_error(exc) from exc
    if not settings.ai_public_chat_enabled:
        return PublicChatOut(
            reply="Chat is currently unavailable. Please contact the team directly.",
            conversation_id="",
            escalated=True,
        )
    try:
        # NOTE: `or` binds tighter than the ternary — parenthesize so a
        # missing visitor_key falls back to the client host (never None).
        fallback_host = request.client.host if request.client else "anon"
        result = chat_service.chat_turn(
            db,
            settings,
            business_id=business.id,
            business_name=business.name,
            channel="web",
            visitor_key=(payload.visitor_key or fallback_host),
            message=payload.message,
            mode="public",
            caller="public",
            run_id=request_id(request),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return PublicChatOut(
        reply=result["reply"],
        conversation_id=result["conversation_id"],
        escalated=result["escalated"],
    )


@router.get(
    "/public/{slug}/business-info", summary="Public business info (tool-backed)"
)
def public_business_info(
    slug: str,
    guarded_slug: str = Depends(require_public_guard("business_info")),
    db: Session = Depends(deps.get_db),
):
    try:
        business = public_service.resolve_public_business(db, slug=guarded_slug)
        profile = ai_tools.execute_tool(
            db,
            business_id=business.id,
            tool_name="get_business_profile",
            args={},
            caller="public",
        )
        hours = ai_tools.execute_tool(
            db,
            business_id=business.id,
            tool_name="get_business_hours",
            args={},
            caller="public",
        )
        location = ai_tools.execute_tool(
            db,
            business_id=business.id,
            tool_name="get_business_location",
            args={},
            caller="public",
        )
        plans = ai_tools.execute_tool(
            db,
            business_id=business.id,
            tool_name="get_membership_plans",
            args={},
            caller="public",
        )
        contact = ai_tools.execute_tool(
            db,
            business_id=business.id,
            tool_name="get_public_contact_information",
            args={},
            caller="public",
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "profile": profile,
        "hours": hours,
        "location": location,
        "plans": plans,
        "contact": contact,
    }


@router.get(
    "/public/{slug}/availability", summary="Public booking availability (real slots)"
)
def public_availability(
    slug: str,
    date: str,
    guarded_slug: str = Depends(require_public_guard("availability")),
    db: Session = Depends(deps.get_db),
):
    try:
        business = public_service.resolve_public_business(db, slug=guarded_slug)
        slots = ai_tools.execute_tool(
            db,
            business_id=business.id,
            tool_name="get_available_booking_slots",
            args={"date": date},
            caller="public",
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return slots


# -- authenticated assistant ----------------------------------------------------


@router.post(
    "/ai/assistant", response_model=AssistOut, summary="Owner/staff AI assistant"
)
def assistant(
    payload: AssistIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.assist")),
) -> AssistOut:
    assert ctx.business is not None
    settings = get_settings()
    try:
        result = chat_service.chat_turn(
            db,
            settings,
            business_id=ctx.business.id,
            business_name=ctx.business.name,
            channel="dashboard",
            visitor_key=str(ctx.user.id),
            message=payload.message,
            mode="owner"
            if str(getattr(ctx, "role_name", "") or "").upper() == "OWNER"
            else "staff",
            caller="staff",
            run_id=request_id(request),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return AssistOut(
        reply=result["reply"],
        tool_calls=result["tool_calls"],
        escalated=result["escalated"],
    )


@router.get("/ai/recommendations", summary="List AI recommendations")
def list_recommendations(
    status: str | None = None,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.read")),
):
    assert ctx.business is not None
    items, total = repo.list_recommendations(
        db, business_id=ctx.business.id, status=status, limit=100
    )
    return {
        "items": [
            {
                "id": r.id,
                "rec_type": r.rec_type,
                "title": r.title,
                "reason": r.reason,
                "confidence": r.confidence,
                "suggested_action": r.suggested_action,
                "status": r.status,
                "risk_level": r.risk_level,
            }
            for r in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@router.post(
    "/ai/recommendations/{rec_id}/decide", summary="Approve/reject recommendation"
)
def decide_recommendation(
    rec_id: str,
    payload: RecommendationDecideIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.manage")),
):
    assert ctx.business is not None
    import uuid as _uuid

    try:
        rid = _uuid.UUID(str(rec_id))
    except ValueError as exc:
        raise map_service_error(exc) from exc
    try:
        row = repo.get_recommendation(db, business_id=ctx.business.id, rec_id=rid)
        if row is None:
            from app.services.errors import NotFoundError

            raise NotFoundError("Recommendation not found.")
        if row.risk_level == "high" and payload.decision == "approved":
            # High-impact actions route through the approvals workflow instead.
            from app.services import approvals as approvals_service

            approvals_service.request_approval(
                db,
                business_id=ctx.business.id,
                data={
                    "entity_type": "ai_recommendation",
                    "entity_id": row.id,
                    "action": "approve",
                    "title": row.title,
                    "reason": row.reason,
                },
                actor_user_id=ctx.user.id,
            )
            row.status = "approved"
        else:
            row.status = payload.decision
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "status": row.status}

"""WhatsApp webhook + send APIs (Block 9 step 44).

GET  /whatsapp/webhook?hub.mode=subscribe&hub.verify_token=...&hub.challenge=...
POST /whatsapp/webhook  (inbound + status updates; signature-verified)
POST /whatsapp/send     (staff-authenticated outbound)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.core.config import get_settings
from app.schemas.blocks812 import SendMessageIn
from app.services import communications as comms
from app.services.authorization import AuthenticatedContext
from app.services.messaging import verify_whatsapp_signature
from app.services import public as public_service

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/webhook", summary="Meta webhook verification")
def verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    settings = get_settings()
    expected = (settings.whatsapp_verify_token or "").strip()
    if hub_mode == "subscribe" and expected and hub_verify_token == expected:
        return Response(content=hub_challenge, media_type="text/plain")
    # Demo mode (no verify token configured): echo challenge for local testing.
    # Production fails closed — an unconfigured webhook never verifies.
    if settings.is_production:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed."
        )
    if hub_mode == "subscribe" and not expected and hub_challenge:
        return Response(content=hub_challenge, media_type="text/plain")
    from fastapi import HTTPException, status

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed."
    )


@router.post("/webhook", summary="WhatsApp inbound webhook")
async def inbound(request: Request, db: Session = Depends(deps.get_db)):
    settings = get_settings()
    raw = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    app_secret = settings.whatsapp_app_secret or ""
    # Fail closed in production: an unconfigured app secret never accepts
    # inbound webhooks (demo mode only outside production).
    if settings.is_production and not app_secret.strip():
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature."
        )
    if not verify_whatsapp_signature(
        app_secret=app_secret, body=raw, signature=signature
    ):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Invalid webhook signature."
        )
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - vendor webhooks must never 500 on bad JSON
        return {"received": True}
    # Meta shape: entry[].changes[].value.{messages[], statuses[]}.
    # Production business resolution: metadata.phone_number_id -> business via
    # per-business operational config (business_settings.operational.whatsapp.
    # phone_number_id) or WHATSAPP_PHONE_NUMBER_MAP. The `business_slug` field
    # is a DEMO/TEST override only (never trusted in production).
    slug = ""
    if isinstance(payload, dict):
        slug = str(payload.get("business_slug", "") or "")
        entries = payload.get("entry", []) or []
    else:
        entries = []
    business = None
    phone_ids = comms.extract_phone_number_ids(
        payload if isinstance(payload, dict) else {}
    )
    for pid in phone_ids:
        try:
            business = comms.resolve_business_for_phone_number_id(
                db, settings, phone_number_id=pid
            )
        except Exception:  # noqa: BLE001 - resolution never breaks the ack
            business = None
        if business is not None:
            break
    if business is None and slug and not settings.is_production:
        try:
            business = public_service.resolve_public_business(db, slug=slug)
        except Exception:  # noqa: BLE001 - unknown slug behaves as no-business
            business = None
    try:
        for entry in entries:
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                for msg in value.get("messages", []) or []:
                    from_me = msg.get("from", "")
                    text = (
                        ((msg.get("text") or {}).get("body", ""))
                        if isinstance(msg.get("text"), dict)
                        else str(msg.get("body", ""))
                    )
                    mid = str(msg.get("id", ""))
                    if business is not None:
                        comms.record_inbound(
                            db,
                            business_id=business.id,
                            channel="whatsapp",
                            external_id=from_me,
                            sender=from_me,
                            body=text,
                            provider_message_id=mid,
                            raw={"webhook": True},
                        )
                for st in value.get("statuses", []) or []:
                    mid = str(st.get("id", ""))
                    status = str(st.get("status", ""))
                    if business is not None and mid:
                        from app.repositories import blocks812 as brepo

                        existing = brepo.get_message_by_provider(
                            db, business_id=business.id, provider_message_id=mid
                        )
                        if existing is not None:
                            existing.status = status
                            brepo.record_delivery(
                                db,
                                business_id=business.id,
                                fields={
                                    "message_id": existing.id,
                                    "provider_message_id": mid,
                                    "status": status,
                                    "raw": {"webhook": True},
                                },
                            )
        db.commit()
    except Exception:  # noqa: BLE001 - webhook processing must never 500; safe ack
        db.rollback()
    return {"received": True}


@router.post("/send", status_code=201, summary="Staff WhatsApp send")
def staff_send(
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
            channel="whatsapp",
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
    return {"id": msg.id, "status": msg.status, "provider": msg.provider}

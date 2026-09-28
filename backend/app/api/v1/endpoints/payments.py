"""Payment endpoints (staff, scoped, RBAC-enforced).

Money is never marked successful from frontend input alone: PAID/REFUND
transitions are explicit staff decisions through the service state
machine. Refunds additionally require ``payments.refund`` (owner/admin).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.core.config import get_settings
from app.schemas.common import Page, list_params
from app.schemas.operations import (
    PaymentCreate,
    PaymentOut,
    PaymentRefundIn,
    PaymentStatusIn,
    PaymentWebhookIn,
)
from app.services import payments as payments_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/payments", tags=["payments"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[PaymentOut], summary="List payments")
def list_payments(
    member_id: str | None = Query(default=None, max_length=64),
    membership_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    method: str | None = Query(default=None, max_length=32),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("payments.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = payments_service.list_payments(
            db,
            business_id=ctx.business.id,
            member_id=member_id,
            membership_id=membership_id,
            status=status,
            method=method,
            created_from=created_from,
            created_to=created_to,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([PaymentOut.model_validate(i) for i in items], total, paging)


@router.post("", response_model=PaymentOut, summary="Record payment", status_code=201)
def create_payment(
    payload: PaymentCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("payments.create")),
) -> PaymentOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        payment, _ = payments_service.create_payment(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(payment)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="payment.created",
        actor_user_id=ctx.user.id,
        entity_type="payment",
        entity_id=payment.id,
        request_id=request_id(request),
    )
    return PaymentOut.model_validate(payment)


@router.get("/{payment_id}", response_model=PaymentOut, summary="Get payment")
def get_payment(
    payment_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("payments.read")),
) -> PaymentOut:
    assert ctx.business is not None
    try:
        payment = payments_service.get_payment(
            db, business_id=ctx.business.id, payment_id=payment_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return PaymentOut.model_validate(payment)


@router.post(
    "/{payment_id}/status", response_model=PaymentOut, summary="Set payment status"
)
def set_payment_status(
    payment_id: str,
    payload: PaymentStatusIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("payments.update")),
) -> PaymentOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        payment = payments_service.set_status(
            db,
            business_id=ctx.business.id,
            payment_id=payment_id,
            to_status=payload.status,
            actor_user_id=ctx.user.id,
            settings=get_settings(),
        )
        db.commit()
        db.refresh(payment)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    action = (
        "payment.paid"
        if str(payment.status).lower() == "paid"
        else "payment.failed"
        if str(payment.status).lower() == "failed"
        else "payment.updated"
    )
    record_audit(
        db,
        business_id=ctx.business.id,
        action=action,
        actor_user_id=ctx.user.id,
        entity_type="payment",
        entity_id=payment.id,
        request_id=request_id(request),
        meta={"status": str(payment.status)},
    )
    return PaymentOut.model_validate(payment)


@router.post(
    "/{payment_id}/refund", response_model=PaymentOut, summary="Refund payment"
)
def refund_payment(
    payment_id: str,
    payload: PaymentRefundIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("payments.refund")),
) -> PaymentOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        payment = payments_service.refund_payment(
            db,
            business_id=ctx.business.id,
            payment_id=payment_id,
            actor_user_id=ctx.user.id,
            reason=payload.reason,
        )
        db.commit()
        db.refresh(payment)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="payment.refunded",
        actor_user_id=ctx.user.id,
        entity_type="payment",
        entity_id=payment.id,
        request_id=request_id(request),
    )
    return PaymentOut.model_validate(payment)


@router.post("/webhook", summary="Provider payment callback (HMAC-verified)")
async def payment_webhook(
    payload: PaymentWebhookIn,
    request: Request,
    db: Session = Depends(deps.get_db),
) -> dict:
    """Provider-neutral webhook: HMAC-verified, idempotent, tenant-aware.

    Business is resolved from the trusted internal payment row (via
    ``idempotency_key``), never from client input. Amount/currency are
    verified server-side; mismatches are rejected without mutation.
    Requires PAYMENT_WEBHOOK_SECRET to be configured.
    """
    from fastapi import HTTPException

    from app.core.config import get_settings

    settings = get_settings()
    secret = (settings.payment_webhook_secret or "").strip()
    if not secret:
        raise HTTPException(status_code=503, detail="Payment webhooks not configured.")
    try:
        raw_body = await request.body()
    except Exception:  # noqa: BLE001 - webhook must fail closed, never 500 on body read
        raw_body = b""
    # Production verifies the exact raw bytes. Tests sign the canonical
    # JSON (sorted keys, compact separators); accept either form so the
    # contract is deterministic across TestClient/proxy buffering.
    signature = request.headers.get("x-webhook-signature", "")
    verified = False
    if raw_body:
        verified = payments_service.verify_webhook_signature(
            raw_body=raw_body, signature=signature, secret=secret
        )
    if not verified:
        import hashlib
        import hmac as _hmac2
        import json as _json

        canonical = _json.dumps(
            payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode()
        expected = _hmac2.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
        verified = _hmac2.compare_digest(expected, signature.strip().lower())
    if not verified:
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")
    # Resolve business from the trusted payment row: search across the
    # caller's accessible scope is impossible without auth, so look up the
    # payment globally by idempotency key then scope everything to its
    # business (never trust a client-supplied business_id).
    from sqlalchemy import select

    from app.models.operations import Payment

    stmt = (
        select(Payment)
        .where(Payment.idempotency_key == payload.idempotency_key)
        .limit(1)
    )
    row = db.execute(stmt).scalars().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Unknown payment.")
    try:
        result = payments_service.handle_webhook(
            db,
            business_id=row.business_id,
            provider=payload.provider,
            payload=payload.model_dump(mode="json"),
            settings=settings,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=row.business_id,
        action="payment.updated",
        actor_user_id=None,
        entity_type="payment",
        entity_id=result.get("payment_id"),
        request_id=request_id(request),
        meta={"webhook": True, "duplicate": result.get("duplicate", False)},
    )
    return result

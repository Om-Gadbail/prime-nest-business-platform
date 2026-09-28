"""Booking endpoints (staff, business-scoped, RBAC-enforced)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.bookings import (
    BookingCreate,
    BookingOut,
    BookingTransitionIn,
    BookingUpdate,
)
from app.schemas.common import Page, list_params
from app.services import bookings as bookings_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/bookings", tags=["bookings"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[BookingOut], summary="List bookings")
def list_bookings(
    status: str | None = Query(default=None, max_length=32),
    booking_type: str | None = Query(default=None, max_length=32),
    assigned_user_id: str | None = Query(default=None, max_length=64),
    start_from: datetime | None = None,
    start_to: datetime | None = None,
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = bookings_service.list_bookings(
            db,
            business_id=ctx.business.id,
            status=status,
            booking_type=booking_type,
            assigned_user_id=assigned_user_id,
            start_from=start_from,
            start_to=start_to,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([BookingOut.model_validate(i) for i in items], total, paging)


@router.post("", response_model=BookingOut, summary="Create booking", status_code=201)
def create_booking(
    payload: BookingCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.create")),
) -> BookingOut:
    assert ctx.business is not None and ctx.user is not None
    data = payload.model_dump(exclude_unset=True)
    contact_id = data.pop("contact_id", None)
    lead_id = data.pop("lead_id", None)
    assigned_user_id = data.pop("assigned_user_id", None)
    try:
        booking = bookings_service.create_booking(
            db,
            business_id=ctx.business.id,
            data=data,
            actor_user_id=ctx.user.id,
            contact_id=contact_id,
            lead_id=lead_id,
            assigned_user_id=assigned_user_id,
        )
        db.commit()
        db.refresh(booking)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="booking.created",
        actor_user_id=ctx.user.id,
        entity_type="booking",
        entity_id=booking.id,
        request_id=request_id(request),
    )
    return BookingOut.model_validate(booking)


@router.get("/{booking_id}", response_model=BookingOut, summary="Get booking")
def get_booking(
    booking_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.read")),
) -> BookingOut:
    assert ctx.business is not None
    try:
        booking = bookings_service.get_booking(
            db, business_id=ctx.business.id, booking_id=booking_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return BookingOut.model_validate(booking)


@router.patch("/{booking_id}", response_model=BookingOut, summary="Update booking")
def update_booking(
    booking_id: str,
    payload: BookingUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.update")),
) -> BookingOut:
    assert ctx.business is not None and ctx.user is not None
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    try:
        booking = bookings_service.update_booking(
            db, business_id=ctx.business.id, booking_id=booking_id, fields=fields
        )
        db.commit()
        db.refresh(booking)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="booking.updated",
        actor_user_id=ctx.user.id,
        entity_type="booking",
        entity_id=booking.id,
        request_id=request_id(request),
    )
    return BookingOut.model_validate(booking)


def _transition(
    db: Session,
    request: Request,
    ctx: AuthenticatedContext,
    booking_id: str,
    to_status: str,
    cancellation_reason: str = "",
) -> BookingOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        booking = bookings_service.transition(
            db,
            business_id=ctx.business.id,
            booking_id=booking_id,
            to_status=to_status,
            actor_user_id=ctx.user.id,
            cancellation_reason=cancellation_reason,
        )
        db.commit()
        db.refresh(booking)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="booking.status_changed",
        actor_user_id=ctx.user.id,
        entity_type="booking",
        entity_id=booking.id,
        request_id=request_id(request),
        meta={"status": str(booking.status)},
    )
    return BookingOut.model_validate(booking)


@router.post(
    "/{booking_id}/confirm", response_model=BookingOut, summary="Confirm booking"
)
def confirm_booking(
    booking_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.update")),
) -> BookingOut:
    return _transition(db, request, ctx, booking_id, "confirmed")


@router.post(
    "/{booking_id}/cancel", response_model=BookingOut, summary="Cancel booking"
)
def cancel_booking(
    booking_id: str,
    payload: BookingTransitionIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.update")),
) -> BookingOut:
    return _transition(
        db,
        request,
        ctx,
        booking_id,
        "cancelled",
        cancellation_reason=payload.cancellation_reason,
    )


@router.post(
    "/{booking_id}/complete", response_model=BookingOut, summary="Complete booking"
)
def complete_booking(
    booking_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.update")),
) -> BookingOut:
    return _transition(db, request, ctx, booking_id, "completed")


@router.post("/{booking_id}/no-show", response_model=BookingOut, summary="Mark no-show")
def no_show_booking(
    booking_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.update")),
) -> BookingOut:
    return _transition(db, request, ctx, booking_id, "no_show")


@router.post(
    "/{booking_id}/reopen", response_model=BookingOut, summary="Re-open booking"
)
def reopen_booking(
    booking_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("bookings.update")),
) -> BookingOut:
    """Explicit staff re-open (cancelled/no-show -> requested only)."""
    return _transition(db, request, ctx, booking_id, "requested")

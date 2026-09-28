"""Seat + allocation endpoints (staff, scoped, RBAC-enforced).

Availability is computed server-side from authoritative DB state; the
frontend never decides what is free. Allocation conflicts surface as
409 (pick another seat) — including the lost-race case.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.operations import (
    SeatAllocateIn,
    SeatAllocationOut,
    SeatAreaCreate,
    SeatAreaOut,
    SeatAvailabilityOut,
    SeatCreate,
    SeatOut,
    SeatTransferIn,
    SeatUpdate,
)
from app.services import seats as seats_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(tags=["seats"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


# -- areas -------------------------------------------------------------------


@router.get("/seat-areas", response_model=Page[SeatAreaOut], summary="List seat areas")
def list_areas(
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.read")),
) -> dict:
    assert ctx.business is not None
    items, total = seats_service.list_areas(
        db,
        business_id=ctx.business.id,
        limit=paging["limit"],
        offset=paging["offset"],
    )
    return _page([SeatAreaOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/seat-areas",
    response_model=SeatAreaOut,
    summary="Create seat area",
    status_code=201,
)
def create_area(
    payload: SeatAreaCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.manage")),
) -> SeatAreaOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        area = seats_service.create_area(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True),
        )
        db.commit()
        db.refresh(area)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="seat.created",
        actor_user_id=ctx.user.id,
        entity_type="seat_area",
        entity_id=area.id,
        request_id=request_id(request),
    )
    return SeatAreaOut.model_validate(area)


# -- seats ----------------------------------------------------------------------


@router.get("/seats", response_model=Page[SeatOut], summary="List seats")
def list_seats(
    area_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    seat_type: str | None = Query(default=None, max_length=32),
    search: str | None = Query(default=None, max_length=64),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = seats_service.list_seats(
            db,
            business_id=ctx.business.id,
            area_id=area_id,
            status=status,
            seat_type=seat_type,
            search=search,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([SeatOut.model_validate(i) for i in items], total, paging)


@router.get(
    "/seats/availability",
    response_model=SeatAvailabilityOut,
    summary="Seat availability (server-computed)",
)
def seat_availability(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.read")),
) -> dict:
    assert ctx.business is not None
    return seats_service.availability(db, business_id=ctx.business.id)


@router.get("/seats/available", summary="Free seats for allocation")
def free_seats(
    seat_type: str | None = Query(default=None, max_length=32),
    area_id: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.read")),
) -> dict:
    from app.schemas.operations import SeatOut as _SeatOut

    assert ctx.business is not None
    try:
        seats = seats_service.available_seats(
            db,
            business_id=ctx.business.id,
            seat_type=seat_type,
            area_id=area_id,
            limit=limit,
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {"items": [_SeatOut.model_validate(s) for s in seats], "total": len(seats)}


@router.post("/seats", response_model=SeatOut, summary="Create seat", status_code=201)
def create_seat(
    payload: SeatCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.manage")),
) -> SeatOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        seat = seats_service.create_seat(
            db,
            business_id=ctx.business.id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(seat)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="seat.created",
        actor_user_id=ctx.user.id,
        entity_type="seat",
        entity_id=seat.id,
        request_id=request_id(request),
    )
    return SeatOut.model_validate(seat)


@router.get("/seats/{seat_id}", response_model=SeatOut, summary="Get seat")
def get_seat(
    seat_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.read")),
) -> SeatOut:
    assert ctx.business is not None
    try:
        seat = seats_service.get_seat(db, business_id=ctx.business.id, seat_id=seat_id)
    except Exception as exc:
        raise map_service_error(exc) from exc
    return SeatOut.model_validate(seat)


@router.patch("/seats/{seat_id}", response_model=SeatOut, summary="Update seat")
def update_seat(
    seat_id: str,
    payload: SeatUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.manage")),
) -> SeatOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        seat = seats_service.update_seat(
            db,
            business_id=ctx.business.id,
            seat_id=seat_id,
            fields=payload.model_dump(exclude_unset=True, mode="json"),
        )
        db.commit()
        db.refresh(seat)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="seat.updated",
        actor_user_id=ctx.user.id,
        entity_type="seat",
        entity_id=seat.id,
        request_id=request_id(request),
    )
    return SeatOut.model_validate(seat)


# -- allocations ---------------------------------------------------------------------


@router.get(
    "/seat-allocations",
    response_model=Page[SeatAllocationOut],
    summary="List seat allocations",
)
def list_allocations(
    seat_id: str | None = Query(default=None, max_length=64),
    member_id: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = seats_service.list_allocations(
            db,
            business_id=ctx.business.id,
            seat_id=seat_id,
            member_id=member_id,
            status=status,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([SeatAllocationOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/seat-allocations",
    response_model=SeatAllocationOut,
    summary="Allocate seat",
    status_code=201,
)
def allocate_seat(
    payload: SeatAllocateIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.manage")),
) -> SeatAllocationOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        allocation = seats_service.allocate_seat(
            db,
            business_id=ctx.business.id,
            seat_id=payload.seat_id,
            member_id=payload.member_id,
            membership_id=payload.membership_id,
            notes=payload.notes,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(allocation)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="seat.allocated",
        actor_user_id=ctx.user.id,
        entity_type="seat_allocation",
        entity_id=allocation.id,
        request_id=request_id(request),
    )
    return SeatAllocationOut.model_validate(allocation)


@router.post(
    "/seat-allocations/{allocation_id}/release",
    response_model=SeatAllocationOut,
    summary="Release seat",
)
def release_seat(
    allocation_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.manage")),
) -> SeatAllocationOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        allocation = seats_service.release_seat(
            db,
            business_id=ctx.business.id,
            allocation_id=allocation_id,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(allocation)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="seat.released",
        actor_user_id=ctx.user.id,
        entity_type="seat_allocation",
        entity_id=allocation.id,
        request_id=request_id(request),
    )
    return SeatAllocationOut.model_validate(allocation)


@router.post(
    "/seat-allocations/{allocation_id}/transfer",
    response_model=SeatAllocationOut,
    summary="Transfer seat",
)
def transfer_seat(
    allocation_id: str,
    payload: SeatTransferIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("seats.manage")),
) -> SeatAllocationOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        replacement = seats_service.transfer_seat(
            db,
            business_id=ctx.business.id,
            allocation_id=allocation_id,
            to_member_id=payload.to_member_id,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(replacement)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="seat.transferred",
        actor_user_id=ctx.user.id,
        entity_type="seat_allocation",
        entity_id=replacement.id,
        request_id=request_id(request),
    )
    return SeatAllocationOut.model_validate(replacement)

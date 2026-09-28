"""Attendance endpoints (staff, scoped, RBAC-enforced)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.operations import AttendanceCorrectIn, AttendanceOut, CheckInIn
from app.services import attendance as attendance_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/attendance", tags=["attendance"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[AttendanceOut], summary="List attendance")
def list_attendance(
    member_id: str | None = Query(default=None, max_length=64),
    day: str | None = Query(default=None, max_length=16),
    day_from: str | None = Query(default=None, max_length=16),
    day_to: str | None = Query(default=None, max_length=16),
    open_only: bool = Query(default=False),
    source: str | None = Query(default=None, max_length=16),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("attendance.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = attendance_service.list_records(
            db,
            business_id=ctx.business.id,
            member_id=member_id,
            day=day,
            day_from=day_from,
            day_to=day_to,
            open_only=open_only,
            source=source,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([AttendanceOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/check-in", response_model=AttendanceOut, summary="Check in", status_code=201
)
def check_in(
    payload: CheckInIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("attendance.create")),
) -> AttendanceOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        row, _ = attendance_service.check_in(
            db,
            business_id=ctx.business.id,
            member_id=payload.member_id,
            data=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="attendance.checked_in",
        actor_user_id=ctx.user.id,
        entity_type="attendance",
        entity_id=row.id,
        request_id=request_id(request),
    )
    return AttendanceOut.model_validate(row)


@router.post(
    "/{attendance_id}/check-out",
    response_model=AttendanceOut,
    summary="Check out",
)
def check_out(
    attendance_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("attendance.create")),
) -> AttendanceOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        row, _ = attendance_service.check_out(
            db,
            business_id=ctx.business.id,
            attendance_id=attendance_id,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="attendance.checked_out",
        actor_user_id=ctx.user.id,
        entity_type="attendance",
        entity_id=row.id,
        request_id=request_id(request),
    )
    return AttendanceOut.model_validate(row)


@router.patch(
    "/{attendance_id}", response_model=AttendanceOut, summary="Correct record"
)
def correct_attendance(
    attendance_id: str,
    payload: AttendanceCorrectIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("attendance.update")),
) -> AttendanceOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        row = attendance_service.correct_record(
            db,
            business_id=ctx.business.id,
            attendance_id=attendance_id,
            fields=payload.model_dump(exclude_unset=True, mode="json"),
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(row)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="attendance.corrected",
        actor_user_id=ctx.user.id,
        entity_type="attendance",
        entity_id=row.id,
        request_id=request_id(request),
    )
    return AttendanceOut.model_validate(row)

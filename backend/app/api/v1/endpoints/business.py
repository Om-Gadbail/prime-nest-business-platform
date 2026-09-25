"""Business + settings endpoints (tenant context derived server-side)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api import deps
from app.schemas.business import BusinessOut, BusinessUpdate, SettingsOut, SettingsUpdate
from app.services import business as business_service
from app.services import settings as settings_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(tags=["business"])


@router.get("/business", response_model=BusinessOut, summary="Current business")
def get_business(
    ctx: AuthenticatedContext = Depends(deps.require_permission("business.read")),
) -> BusinessOut:
    assert ctx.business is not None
    return BusinessOut.model_validate(ctx.business)


@router.patch("/business", response_model=BusinessOut, summary="Update current business")
def patch_business(
    payload: BusinessUpdate,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("business.update")),
) -> BusinessOut:
    assert ctx.business is not None
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    try:
        updated = business_service.update_business(db, business=ctx.business, fields=fields)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return BusinessOut.model_validate(updated)


@router.get("/business/settings", response_model=SettingsOut, summary="Get business settings")
def get_settings(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("settings.read")),
) -> SettingsOut:
    assert ctx.business is not None
    row = settings_service.get_settings(db, business_id=ctx.business.id)
    return SettingsOut.model_validate(row)


@router.patch(
    "/business/settings", response_model=SettingsOut, summary="Update business settings"
)
def patch_settings(
    payload: SettingsUpdate,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("settings.update")),
) -> SettingsOut:
    assert ctx.business is not None
    data = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if v is not None}
    try:
        updated = settings_service.update_settings(
            db, business_id=ctx.business.id, payload=data
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return SettingsOut.model_validate(updated)

"""Contact endpoints (staff, business-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.crm import ContactCreate, ContactOut, ContactUpdate
from app.services import crm as crm_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/contacts", tags=["contacts"])


@router.get("", response_model=Page[ContactOut], summary="List contacts")
def list_contacts(
    search: str | None = Query(default=None, max_length=64),
    status: str | None = Query(default=None, max_length=32),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("contacts.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = crm_service.list_contacts(
            db,
            business_id=ctx.business.id,
            search=search,
            status=status,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [ContactOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.post("", response_model=ContactOut, summary="Create contact", status_code=201)
def create_contact(
    payload: ContactCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("contacts.create")),
) -> ContactOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        contact = crm_service.create_contact(
            db,
            business_id=ctx.business.id,
            **payload.model_dump(exclude_unset=True),
        )
        db.commit()
        db.refresh(contact)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="contact.created",
        actor_user_id=ctx.user.id,
        entity_type="contact",
        entity_id=contact.id,
        request_id=request_id(request),
    )
    return ContactOut.model_validate(contact)


@router.get("/{contact_id}", response_model=ContactOut, summary="Get contact")
def get_contact(
    contact_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("contacts.read")),
) -> ContactOut:
    assert ctx.business is not None
    try:
        contact = crm_service.get_contact(
            db, business_id=ctx.business.id, contact_id=contact_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return ContactOut.model_validate(contact)


@router.patch("/{contact_id}", response_model=ContactOut, summary="Update contact")
def update_contact(
    contact_id: str,
    payload: ContactUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("contacts.update")),
) -> ContactOut:
    assert ctx.business is not None and ctx.user is not None
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    try:
        contact = crm_service.update_contact(
            db, business_id=ctx.business.id, contact_id=contact_id, fields=fields
        )
        db.commit()
        db.refresh(contact)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="contact.updated",
        actor_user_id=ctx.user.id,
        entity_type="contact",
        entity_id=contact.id,
        request_id=request_id(request),
    )
    return ContactOut.model_validate(contact)

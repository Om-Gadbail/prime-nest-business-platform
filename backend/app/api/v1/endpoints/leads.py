"""Lead endpoints (staff, business-scoped, RBAC-enforced)."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.crm import CustomerOut
from app.schemas.leads import (
    LeadActivityOut,
    LeadAssignIn,
    LeadConvertIn,
    LeadCreate,
    LeadNoteIn,
    LeadOut,
    LeadStatusIn,
    LeadUpdate,
)
from app.schemas.ops import LeadTransferIn
from app.services import leads as leads_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/leads", tags=["leads"])


def _page(items: list, total: int, paging: dict) -> dict:
    return {
        "items": items,
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.get("", response_model=Page[LeadOut], summary="List leads")
def list_leads(
    status: str | None = Query(default=None, max_length=32),
    source: str | None = Query(default=None, max_length=32),
    assigned_user_id: str | None = Query(default=None, max_length=64),
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    follow_up_from: datetime | None = None,
    follow_up_to: datetime | None = None,
    search: str | None = Query(default=None, max_length=64),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = leads_service.list_leads(
            db,
            business_id=ctx.business.id,
            status=status,
            source=source,
            assigned_user_id=assigned_user_id,
            created_from=created_from,
            created_to=created_to,
            follow_up_from=follow_up_from,
            follow_up_to=follow_up_to,
            search=search,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([LeadOut.model_validate(i) for i in items], total, paging)


@router.post("", response_model=LeadOut, summary="Create lead", status_code=201)
def create_lead(
    payload: LeadCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.create")),
) -> LeadOut:
    assert ctx.business is not None and ctx.user is not None
    data = payload.model_dump(exclude_unset=True)
    contact_id = data.pop("contact_id", None)
    assigned_user_id = data.pop("assigned_user_id", None)
    try:
        lead = leads_service.create_lead(
            db,
            business_id=ctx.business.id,
            data=data,
            actor_user_id=ctx.user.id,
            contact_id=contact_id,
            assigned_user_id=assigned_user_id,
        )
        db.commit()
        db.refresh(lead)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.created",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead.id,
        request_id=request_id(request),
    )
    return LeadOut.model_validate(lead)


@router.get("/{lead_id}", response_model=LeadOut, summary="Get lead")
def get_lead(
    lead_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.read")),
) -> LeadOut:
    assert ctx.business is not None
    try:
        lead = leads_service.get_lead(db, business_id=ctx.business.id, lead_id=lead_id)
    except Exception as exc:
        raise map_service_error(exc) from exc
    return LeadOut.model_validate(lead)


@router.patch("/{lead_id}", response_model=LeadOut, summary="Update lead")
def update_lead(
    lead_id: str,
    payload: LeadUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.update")),
) -> LeadOut:
    assert ctx.business is not None and ctx.user is not None
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    try:
        lead = leads_service.update_lead(
            db, business_id=ctx.business.id, lead_id=lead_id, fields=fields
        )
        db.commit()
        db.refresh(lead)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.updated",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead.id,
        request_id=request_id(request),
    )
    return LeadOut.model_validate(lead)


@router.post("/{lead_id}/assign", response_model=LeadOut, summary="Assign lead")
def assign_lead(
    lead_id: str,
    payload: LeadAssignIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.update")),
) -> LeadOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        lead = leads_service.assign_lead(
            db,
            business_id=ctx.business.id,
            lead_id=lead_id,
            assignee_user_id=payload.assigned_user_id,
            actor_user_id=ctx.user.id,
        )
        db.commit()
        db.refresh(lead)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.assigned",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead.id,
        request_id=request_id(request),
        meta={"assigned_to": str(payload.assigned_user_id)},
    )
    return LeadOut.model_validate(lead)


@router.post("/{lead_id}/status", response_model=LeadOut, summary="Change lead status")
def change_status(
    lead_id: str,
    payload: LeadStatusIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.update")),
) -> LeadOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        lead = leads_service.set_status(
            db,
            business_id=ctx.business.id,
            lead_id=lead_id,
            to_status=payload.status,
            actor_user_id=ctx.user.id,
            lost_reason=payload.lost_reason,
            note=payload.note,
        )
        db.commit()
        db.refresh(lead)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.status_changed",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead.id,
        request_id=request_id(request),
        meta={"status": str(lead.status)},
    )
    return LeadOut.model_validate(lead)


@router.post(
    "/{lead_id}/notes",
    response_model=LeadActivityOut,
    summary="Add lead note",
    status_code=201,
)
def add_note(
    lead_id: str,
    payload: LeadNoteIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.update")),
) -> LeadActivityOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        activity = leads_service.add_note(
            db,
            business_id=ctx.business.id,
            lead_id=lead_id,
            note=payload.note,
            actor_user_id=ctx.user.id,
            activity_type=payload.activity_type,
        )
        db.commit()
        db.refresh(activity)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.note_added",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead_id,
        request_id=request_id(request),
    )
    return LeadActivityOut.model_validate(activity)


@router.get(
    "/{lead_id}/activities",
    response_model=Page[LeadActivityOut],
    summary="Lead activity history",
)
def list_activities(
    lead_id: str,
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = leads_service.list_activities(
            db,
            business_id=ctx.business.id,
            lead_id=lead_id,
            limit=paging["limit"],
            offset=paging["offset"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return _page([LeadActivityOut.model_validate(i) for i in items], total, paging)


@router.post(
    "/{lead_id}/convert", response_model=CustomerOut, summary="Convert lead to customer"
)
def convert_lead(
    lead_id: str,
    payload: LeadConvertIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.update")),
    _ctx2: AuthenticatedContext = Depends(deps.require_permission("customers.create")),
) -> CustomerOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        customer = leads_service.convert_lead(
            db,
            business_id=ctx.business.id,
            lead_id=lead_id,
            actor_user_id=ctx.user.id,
            customer_notes=payload.customer_notes,
        )
        db.commit()
        db.refresh(customer)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.converted",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead_id,
        request_id=request_id(request),
    )
    return CustomerOut.model_validate(customer)


@router.post(
    "/{lead_id}/transfer",
    response_model=LeadOut,
    summary="Transfer lead to another business (OWNER/ADMIN)",
)
def transfer_lead(
    lead_id: str,
    payload: LeadTransferIn,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("leads.transfer")),
) -> LeadOut:
    """Explicit audited cross-business transfer.

    Requires ``leads.transfer`` AND OWNER/ADMIN role (defense in depth).
    Creates a linked copy in the target business; the source row stays.
    """
    assert ctx.business is not None and ctx.user is not None
    if ctx.role_name not in ("OWNER", "ADMIN"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cross-business transfer requires OWNER or ADMIN.",
        )
    try:
        from app.services import lead_routing as routing_service

        _source, new_lead = routing_service.transfer_lead(
            db,
            source_business_id=ctx.business.id,
            lead_id=lead_id,
            target_slug=payload.target_business_slug,
            reason=payload.reason,
            actor_user_id=ctx.user.id,
            actor_role=ctx.role_name,
        )
        db.commit()
        db.refresh(new_lead)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    rid = request_id(request)
    record_audit(
        db,
        business_id=ctx.business.id,
        action="lead.transferred",
        actor_user_id=ctx.user.id,
        entity_type="lead",
        entity_id=lead_id,
        request_id=rid,
        meta={"target": payload.target_business_slug, "direction": "out"},
    )
    try:
        record_audit(
            db,
            business_id=new_lead.business_id,
            action="lead.transferred",
            actor_user_id=ctx.user.id,
            entity_type="lead",
            entity_id=new_lead.id,
            request_id=rid,
            meta={"source": ctx.business.slug, "direction": "in"},
        )
    except Exception:  # noqa: BLE001 - inbound trail is best-effort
        pass
    return LeadOut.model_validate(new_lead)

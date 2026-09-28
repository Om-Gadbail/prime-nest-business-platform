"""Customer endpoints (staff, business-scoped)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.crm import CustomerCreate, CustomerOut, CustomerUpdate
from app.services import crm as crm_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/customers", tags=["customers"])


@router.get("", response_model=Page[CustomerOut], summary="List customers")
def list_customers(
    status: str | None = Query(default=None, max_length=32),
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("customers.read")),
) -> dict:
    assert ctx.business is not None
    try:
        items, total = crm_service.list_customers(
            db,
            business_id=ctx.business.id,
            status=status,
            limit=paging["limit"],
            offset=paging["offset"],
            sort=paging["sort"],
            direction=paging["direction"],
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return {
        "items": [CustomerOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }


@router.post("", response_model=CustomerOut, summary="Create customer", status_code=201)
def create_customer(
    payload: CustomerCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("customers.create")),
) -> CustomerOut:
    assert ctx.business is not None and ctx.user is not None
    try:
        customer = crm_service.create_customer(
            db,
            business_id=ctx.business.id,
            contact_id=payload.contact_id,
            status=payload.status,
            customer_since=payload.customer_since,
            notes=payload.notes,
        )
        db.commit()
        db.refresh(customer)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="customer.created",
        actor_user_id=ctx.user.id,
        entity_type="customer",
        entity_id=customer.id,
        request_id=request_id(request),
    )
    return CustomerOut.model_validate(customer)


@router.get("/{customer_id}", response_model=CustomerOut, summary="Get customer")
def get_customer(
    customer_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("customers.read")),
) -> CustomerOut:
    assert ctx.business is not None
    try:
        customer = crm_service.get_customer(
            db, business_id=ctx.business.id, customer_id=customer_id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return CustomerOut.model_validate(customer)


@router.patch("/{customer_id}", response_model=CustomerOut, summary="Update customer")
def update_customer(
    customer_id: str,
    payload: CustomerUpdate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("customers.update")),
) -> CustomerOut:
    assert ctx.business is not None and ctx.user is not None
    fields = {k: v for k, v in payload.model_dump(exclude_unset=True).items()}
    try:
        customer = crm_service.update_customer(
            db, business_id=ctx.business.id, customer_id=customer_id, fields=fields
        )
        db.commit()
        db.refresh(customer)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="customer.updated",
        actor_user_id=ctx.user.id,
        entity_type="customer",
        entity_id=customer.id,
        request_id=request_id(request),
    )
    return CustomerOut.model_validate(customer)

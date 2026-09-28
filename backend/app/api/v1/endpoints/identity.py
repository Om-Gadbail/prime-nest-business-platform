"""Unified-identity endpoints (Block 3, step 14).

- Business-scoped reads (own business slice) need ``contacts.read``.
- Cross-business visibility needs ``identity.read`` (OWNER/ADMIN only).
- Manual linking needs ``identity.read`` (OWNER/ADMIN role enforced in
  the service too — defense in depth).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, record_audit, request_id
from app.schemas.common import Page, list_params
from app.schemas.ops import (
    CrossBusinessPersonOut,
    IdentityLinkCreate,
    IdentityLinkOut,
    PersonOut,
)
from app.services import identity as identity_service
from app.services.authorization import AuthenticatedContext

router = APIRouter(prefix="/identity", tags=["identity"])


@router.get(
    "/persons/{person_id}", response_model=PersonOut, summary="Person (own business)"
)
def get_person(
    person_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("contacts.read")),
) -> PersonOut:
    assert ctx.business is not None
    try:
        view = identity_service.person_overview(
            db, person_id=person_id, business_id=ctx.business.id
        )
    except Exception as exc:
        raise map_service_error(exc) from exc
    return PersonOut(**view)


@router.get(
    "/persons/{person_id}/cross-business",
    response_model=CrossBusinessPersonOut,
    summary="Person across businesses (privileged)",
)
def get_person_cross_business(
    person_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("identity.read")),
) -> CrossBusinessPersonOut:
    try:
        view = identity_service.cross_business_overview(db, person_id=person_id)
    except Exception as exc:
        raise map_service_error(exc) from exc
    return CrossBusinessPersonOut(**view)


@router.post("/links", response_model=IdentityLinkOut, summary="Manual identity link")
def create_link(
    payload: IdentityLinkCreate,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("identity.read")),
) -> IdentityLinkOut:
    assert ctx.business is not None and ctx.user is not None
    if ctx.role_name not in ("OWNER", "ADMIN"):
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Manual identity linking requires OWNER or ADMIN.",
        )
    try:
        link = identity_service.manual_link(
            db,
            business_id=ctx.business.id,
            contact_id=payload.contact_id,
            person_id=payload.person_id,
            actor_user_id=ctx.user.id,
            note=payload.note,
        )
        db.commit()
        db.refresh(link)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    record_audit(
        db,
        business_id=ctx.business.id,
        action="identity.linked",
        actor_user_id=ctx.user.id,
        entity_type="identity_link",
        entity_id=link.id,
        request_id=request_id(request),
        meta={"contact_id": str(payload.contact_id)},
    )
    return IdentityLinkOut.model_validate(link)


@router.get(
    "/links", response_model=Page[IdentityLinkOut], summary="List identity links"
)
def list_links(
    paging: dict = Depends(list_params),
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("contacts.read")),
) -> dict:
    assert ctx.business is not None
    from app.repositories import persons as persons_repo

    items, total = persons_repo.list_business_links(
        db,
        business_id=ctx.business.id,
        limit=paging["limit"],
        offset=paging["offset"],
    )
    return {
        "items": [IdentityLinkOut.model_validate(i) for i in items],
        "total": total,
        "limit": paging["limit"],
        "offset": paging["offset"],
    }

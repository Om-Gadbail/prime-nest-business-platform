"""AI insight endpoints (advisory, provider-neutral, disabled by default).

With AI_ENABLED=false these return 503 (the rest of the platform works
fully). With AI_ENABLED=true and the default noop provider they return
deterministic mock insights labeled provider="noop" — never presented as
real AI. No endpoint here mutates business data.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, request_id
from app.core.config import get_settings
from app.schemas.ai import (
    AIModeOut,
    CustomerInsightOut,
    LeadClassificationOut,
    LeadSummaryOut,
    OperationalRecommendationOut,
)
from app.services import bookings as bookings_service
from app.services import crm as crm_service
from app.services import leads as leads_service
from app.services.ai.service import AIService
from app.services.authorization import AuthenticatedContext
from app.services.errors import AIProviderError

router = APIRouter(prefix="/ai", tags=["ai"])


def _service() -> AIService:
    return AIService(get_settings())


@router.get("/mode", response_model=AIModeOut, summary="AI mode")
def ai_mode(
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.read")),
) -> AIModeOut:
    service = _service()
    return AIModeOut(
        enabled=service.enabled,
        mode=service.mode,
        provider=service.provider_name,
        capabilities=["lead_summary", "lead_classification"] if service.enabled else [],
    )


@router.post(
    "/leads/{lead_id}/summary",
    response_model=LeadSummaryOut,
    summary="Advisory lead summary",
)
def lead_summary(
    lead_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.read")),
) -> LeadSummaryOut:
    assert ctx.business is not None
    service = _service()
    try:
        lead = leads_service.get_lead(db, business_id=ctx.business.id, lead_id=lead_id)
        insight = service.summarize_lead(
            db,
            business_id=ctx.business.id,
            lead=lead,
            request_id=request_id(request),
        )
        db.commit()
    except AIProviderError as exc:
        # Durable error audit: the failed run metadata commits even though
        # the insight itself failed (atomicity applies to business data).
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise map_service_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return LeadSummaryOut(mode=service.mode, insight=insight)


@router.post(
    "/leads/{lead_id}/classification",
    response_model=LeadClassificationOut,
    summary="Advisory lead classification",
)
def lead_classification(
    lead_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.read")),
) -> LeadClassificationOut:
    assert ctx.business is not None
    service = _service()
    try:
        lead = leads_service.get_lead(db, business_id=ctx.business.id, lead_id=lead_id)
        insight = service.classify_lead(
            db,
            business_id=ctx.business.id,
            lead=lead,
            request_id=request_id(request),
        )
        db.commit()
    except AIProviderError as exc:
        # Durable error audit: the failed run metadata commits even though
        # the insight itself failed (atomicity applies to business data).
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise map_service_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return LeadClassificationOut(mode=service.mode, insight=insight)


@router.post(
    "/customers/{customer_id}/insight",
    response_model=CustomerInsightOut,
    summary="Advisory customer insight",
)
def customer_insight(
    customer_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.read")),
) -> CustomerInsightOut:
    assert ctx.business is not None
    service = _service()
    try:
        customer = crm_service.get_customer(
            db, business_id=ctx.business.id, customer_id=customer_id
        )
        insight = service.customer_insight(
            db,
            business_id=ctx.business.id,
            customer=customer,
            request_id=request_id(request),
        )
        db.commit()
    except AIProviderError as exc:
        # Durable error audit: the failed run metadata commits even though
        # the insight itself failed (atomicity applies to business data).
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise map_service_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return CustomerInsightOut(mode=service.mode, insight=insight)


@router.post(
    "/bookings/{booking_id}/recommendation",
    response_model=OperationalRecommendationOut,
    summary="Advisory operational recommendation",
)
def booking_recommendation(
    booking_id: str,
    request: Request,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("ai.read")),
) -> OperationalRecommendationOut:
    assert ctx.business is not None
    service = _service()
    try:
        booking = bookings_service.get_booking(
            db, business_id=ctx.business.id, booking_id=booking_id
        )
        insight = service.operational_recommendation(
            db,
            business_id=ctx.business.id,
            booking=booking,
            request_id=request_id(request),
        )
        db.commit()
    except AIProviderError as exc:
        # Durable error audit: the failed run metadata commits even though
        # the insight itself failed (atomicity applies to business data).
        try:
            db.commit()
        except SQLAlchemyError:
            db.rollback()
        raise map_service_error(exc) from exc
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return OperationalRecommendationOut(mode=service.mode, insight=insight)

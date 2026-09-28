"""Growth APIs (Block 11) + analytics/intelligence APIs (Block 12) + owner brief."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.schemas.blocks812 import AttributionIn, ConsentIn, CrossSellIn, ReferralIn
from app.services import analytics as analytics_service
from app.services import growth as growth_service
from app.services import reports as reports_service
from app.services.authorization import AuthenticatedContext
from app.repositories import blocks812 as repo

growth_router = APIRouter(prefix="/growth", tags=["growth"])
analytics_router = APIRouter(prefix="/analytics", tags=["analytics"])
brief_router = APIRouter(prefix="/owner", tags=["owner-brief"])


@growth_router.get("/sources", summary="List growth sources")
def list_sources(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.read")),
):
    assert ctx.business is not None
    items = repo.list_sources(db, business_id=ctx.business.id)
    return {
        "items": [
            {"id": s.id, "code": s.code, "name": s.name, "is_active": s.is_active}
            for s in items
        ]
    }


@growth_router.post("/attributions", status_code=201, summary="Record attribution")
def record_attribution(
    payload: AttributionIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.manage")),
):
    assert ctx.business is not None
    try:
        row = growth_service.record_attribution(
            db,
            business_id=ctx.business.id,
            subject_type=payload.subject_type,
            subject_id=payload.subject_id,
            source_code=payload.source_code,
            campaign=payload.campaign,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "source_code": row.source_code}


@growth_router.get("/funnel", summary="Attribution funnel by source")
def funnel(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.read")),
):
    assert ctx.business is not None
    return {"funnel": repo.funnel_by_source(db, business_id=ctx.business.id)}


@growth_router.post("/referrals", status_code=201, summary="Create referral")
def create_referral(
    payload: ReferralIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.manage")),
):
    assert ctx.business is not None
    try:
        row = growth_service.create_referral(
            db, business_id=ctx.business.id, fields=payload.model_dump()
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {
        "id": row.id,
        "status": row.status,
        "referred_lead_id": row.referred_lead_id,
    }


@growth_router.get("/referrals", summary="List referrals")
def list_referrals(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.read")),
):
    assert ctx.business is not None
    items, total = repo.list_referrals(db, business_id=ctx.business.id, limit=100)
    return {
        "items": [
            {
                "id": r.id,
                "referrer_name": r.referrer_name,
                "referred_name": r.referred_name,
                "status": r.status,
            }
            for r in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@growth_router.post("/referrals/{referral_id}/convert", summary="Convert referral")
def convert_referral(
    referral_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.manage")),
):
    assert ctx.business is not None
    try:
        row = growth_service.convert_referral(
            db, business_id=ctx.business.id, referral_id=referral_id
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "status": row.status}


@growth_router.post(
    "/cross-sell", status_code=201, summary="Create cross-sell opportunity"
)
def create_xsell(
    payload: CrossSellIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.manage")),
):
    assert ctx.business is not None
    try:
        row = growth_service.evaluate_cross_sell(
            db,
            business_id=ctx.business.id,
            target_business_id=payload.target_business_id,
            member_id=payload.member_id,
            customer_id=payload.customer_id,
            lead_id=payload.lead_id,
            reason=payload.reason,
            offer=payload.offer,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "status": row.status}


@growth_router.get("/cross-sell", summary="List cross-sell opportunities")
def list_xsell(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.read")),
):
    assert ctx.business is not None
    items, total = repo.list_xsell(db, business_id=ctx.business.id, limit=100)
    return {
        "items": [
            {
                "id": r.id,
                "target_business_id": r.target_business_id,
                "status": r.status,
                "consent": r.consent,
                "offer": r.offer,
            }
            for r in items
        ],
        "total": total,
        "limit": 100,
        "offset": 0,
    }


@growth_router.post("/cross-sell/{opp_id}/consent", summary="Record cross-sell consent")
def xsell_consent(
    opp_id: str,
    payload: ConsentIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.manage")),
):
    assert ctx.business is not None
    try:
        row = growth_service.set_xsell_consent(
            db,
            business_id=ctx.business.id,
            opportunity_id=opp_id,
            consent=payload.consent,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "status": row.status, "consent": row.consent}


@growth_router.post("/cross-sell/{opp_id}/convert", summary="Convert cross-sell")
def xsell_convert(
    opp_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.manage")),
):
    assert ctx.business is not None
    try:
        row = growth_service.convert_xsell(
            db, business_id=ctx.business.id, opportunity_id=opp_id
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": row.id, "status": row.status}


@growth_router.get("/relationships", summary="List business relationships")
def list_relationships(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("growth.read")),
):
    assert ctx.business is not None
    items = repo.list_relationships(db, business_id=ctx.business.id)
    return {
        "items": [
            {
                "id": r.id,
                "from_business_id": r.from_business_id,
                "to_business_id": r.to_business_id,
                "rel_type": r.rel_type,
                "is_active": r.is_active,
            }
            for r in items
        ]
    }


@analytics_router.get("/metrics", summary="Business metrics (real aggregates)")
def metrics(
    days: int = 30,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("analytics.read")),
):
    assert ctx.business is not None
    try:
        return analytics_service.compute_metrics(
            db, business_id=ctx.business.id, days=min(365, max(1, days))
        )
    except Exception as exc:
        raise map_service_error(exc) from exc


@analytics_router.get("/intelligence", summary="Performance/revenue intelligence")
def intelligence(
    days: int = 30,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("analytics.read")),
):
    assert ctx.business is not None
    try:
        return analytics_service.intelligence(
            db, business_id=ctx.business.id, days=min(365, max(1, days))
        )
    except Exception as exc:
        raise map_service_error(exc) from exc


@analytics_router.get(
    "/lead/{lead_id}/intelligence",
    summary="Lead intelligence (fact/signal/recommendation)",
)
def lead_intel(
    lead_id: str,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("analytics.read")),
):
    assert ctx.business is not None
    try:
        from app.services import leads as leads_service

        lead = leads_service.get_lead(db, business_id=ctx.business.id, lead_id=lead_id)
        return analytics_service.lead_intelligence(
            db, business_id=ctx.business.id, lead=lead
        )
    except Exception as exc:
        raise map_service_error(exc) from exc


@brief_router.get(
    "/brief", summary="Daily owner brief (yesterday/today/trend/exceptions/actions)"
)
def owner_brief(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("reports.read")),
):
    assert ctx.business is not None
    try:
        report = reports_service.build_daily_report(db, business_id=ctx.business.id)
        # Prompt 7: optional Gemini narrative enhancement. The deterministic
        # numbers above stay authoritative; when Gemini is unavailable the
        # brief works unchanged (no ai_summary key claims).
        try:
            from app.core.config import get_settings as _get_settings
            from app.services import growth_engine as _growth

            facts = {
                "business": str(getattr(ctx.business, "name", "") or ""),
                "yesterday": dict(report.get("yesterday", {}) or {}),
                "today": dict(report.get("today", {}) or {}),
                "trend": dict(report.get("trend", {}) or {}),
                "recommended_actions": list(
                    report.get("recommended_actions", []) or []
                )[:5],
            }
            enhancement = _growth.enhance_brief_with_gemini(
                _get_settings(), business_id=ctx.business.id, facts=facts
            )
            if enhancement.get("ai_summary"):
                report["ai_summary"] = enhancement["ai_summary"]
            report["ai_available"] = bool(enhancement.get("ai_available", False))
        except Exception:  # noqa: BLE001 - enhancement never breaks the brief
            pass
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return report


@brief_router.get("/renewals/scan", summary="Renewal scan at configured offsets")
def renewal_scan(
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(deps.require_permission("reports.read")),
):
    assert ctx.business is not None
    try:
        return {"due": reports_service.renewal_scan(db, business_id=ctx.business.id)}
    except Exception as exc:
        raise map_service_error(exc) from exc

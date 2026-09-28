"""Public anonymous intake (website-safe, slug-addressed, abuse-protected).

Pipeline per POST: content-type -> body size -> rate limit -> resolve
active business -> feature flag -> honeypot -> idempotency -> intake ->
notify -> minimal safe response. Failures use the standard safe envelope.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error, request_id
from app.core.config import Settings, get_settings
from app.schemas.public import (
    PublicBookingIn,
    PublicBookingOut,
    PublicConfigOut,
    PublicLeadIn,
    PublicLeadOut,
)
from app.services import bookings as bookings_service
from app.services import idempotency as idem_service
from app.services import leads as leads_service
from app.services import lead_routing as routing_service
from app.services import public as public_service
from app.services import rate_limit as rate_limit_service
from app.services.security_log import security_event

router = APIRouter(prefix="/public", tags=["public"])


def _check_content_type(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type != "application/json":
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Content-Type must be application/json.",
        )


def _guard(request: Request, settings: Settings, *, endpoint: str, slug: str) -> None:
    # Size is enforced pre-parse by BodySizeLimitMiddleware; content-type and
    # rate limits are enforced here (dependencies run before endpoint code).
    _check_content_type(request)
    try:
        rate_limit_service.enforce_public(
            settings, request=request, endpoint=endpoint, business_slug=slug
        )
    except Exception as exc:
        security_event(
            "public.rate_limited",
            request_id=request_id(request),
            business_slug=slug,
            extra={"endpoint": endpoint},
        )
        raise map_service_error(exc) from exc


def require_public_guard(endpoint: str):
    """Dependency factory: runs abuse guards BEFORE FastAPI parses the body.

    Body parsing (Pydantic) happens after dependencies, so content-type /
    size / rate-limit rejections surface as 415/413/429 instead of being
    masked by 422 body-validation errors. Returns the normalized slug.
    """

    def _dep(request: Request) -> str:
        settings = get_settings()
        try:
            clean_slug = public_service.normalize_slug(
                request.path_params.get("slug", "")
            )
        except Exception as exc:
            raise map_service_error(exc) from exc
        _guard(request, settings, endpoint=endpoint, slug=clean_slug)
        return clean_slug

    return _dep


def _honeypot_hit(
    payload: object, *, request: Request, slug: str, endpoint: str
) -> bool:
    trap = str(getattr(payload, "website_url", "") or "").strip()
    if trap:
        security_event(
            "public.honeypot",
            request_id=request_id(request),
            business_slug=slug,
            extra={"endpoint": endpoint},
        )
        return True
    return False


@router.get(
    "/{slug}/config", response_model=PublicConfigOut, summary="Public business config"
)
def public_config(slug: str, db: Session = Depends(deps.get_db)) -> PublicConfigOut:
    try:
        config = public_service.public_config(db, slug=slug)
    except Exception as exc:
        raise map_service_error(exc) from exc
    return PublicConfigOut(**config)


@router.post(
    "/{slug}/leads",
    response_model=PublicLeadOut,
    summary="Submit public enquiry",
    status_code=201,
)
def submit_lead(
    slug: str,
    payload: PublicLeadIn,
    request: Request,
    clean_slug: str = Depends(require_public_guard("public-lead")),
    db: Session = Depends(deps.get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PublicLeadOut:
    try:
        if _honeypot_hit(
            payload, request=request, slug=clean_slug, endpoint="public-lead"
        ):
            # Fake success: bots must not learn the trap exists; nothing stored.
            return PublicLeadOut(lead_id="received")
        business = public_service.resolve_public_business(db, slug=clean_slug)
        public_service.require_feature(
            db, business=business, flag="lead_capture_enabled", feature="Lead capture"
        )
        key = idem_service.validate_key(idempotency_key)
        data = payload.model_dump(exclude={"website_url"})
        record, replay_body, replay_status = idem_service.acquire(
            db,
            business_id=business.id,
            endpoint="public-lead",
            idem_key=key,
            payload=data,
        )
        if replay_body is not None and replay_status is not None:
            db.rollback()  # nothing was written; release the savepoint state
            return PublicLeadOut(**replay_body)
        message = (data.get("message") or "").strip()
        if data.get("preferred_time"):
            message = f"{message}\nPreferred time: {data['preferred_time']}".strip()
        _, route_reason = routing_service.resolve_by_slug(db, slug=clean_slug)
        lead = leads_service.intake_lead(
            db,
            business_id=business.id,
            data={**data, "display_name": data.get("name", ""), "message": message},
            routing={"routed_by": "slug", "reason": route_reason},
        )
        db.flush()
        response = PublicLeadOut(lead_id=str(lead.id))
        idem_service.complete(
            db,
            record=record,
            response_status=201,
            response_body=response.model_dump(),
        )
        _audit_intake(
            db,
            business_id=business.id,
            action="lead.created",
            entity_type="lead",
            entity_id=lead.id,
            request=request,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return response


@router.post(
    "/{slug}/bookings",
    response_model=PublicBookingOut,
    summary="Submit public booking request",
    status_code=201,
)
def submit_booking(
    slug: str,
    payload: PublicBookingIn,
    request: Request,
    clean_slug: str = Depends(require_public_guard("public-booking")),
    db: Session = Depends(deps.get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> PublicBookingOut:
    try:
        if _honeypot_hit(
            payload, request=request, slug=clean_slug, endpoint="public-booking"
        ):
            return PublicBookingOut(booking_id="received")
        business = public_service.resolve_public_business(db, slug=clean_slug)
        public_service.require_feature(
            db, business=business, flag="booking_enabled", feature="Booking requests"
        )
        key = idem_service.validate_key(idempotency_key)
        data = payload.model_dump(exclude={"website_url"})
        record, replay_body, replay_status = idem_service.acquire(
            db,
            business_id=business.id,
            endpoint="public-booking",
            idem_key=key,
            payload=data,
        )
        if replay_body is not None and replay_status is not None:
            db.rollback()
            return PublicBookingOut(**replay_body)
        message = (data.get("message") or "").strip()
        if data.get("preferred_time_label"):
            message = (
                f"{message}\nPreferred time: {data['preferred_time_label']}".strip()
            )
        attribution = _attribution_suffix(data)
        if attribution:
            message = f"{message}\n{attribution}".strip()
        booking = bookings_service.intake_booking(
            db,
            business_id=business.id,
            data={**data, "display_name": data.get("name", ""), "message": message},
        )
        db.flush()
        # Honest language: intake creates REQUESTED, never a confirmation.
        response = PublicBookingOut(booking_id=str(booking.id))
        idem_service.complete(
            db,
            record=record,
            response_status=201,
            response_body=response.model_dump(),
        )
        _audit_intake(
            db,
            business_id=business.id,
            action="booking.created",
            entity_type="booking",
            entity_id=booking.id,
            request=request,
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return response


def _audit_intake(db, *, business_id, action, entity_type, entity_id, request) -> None:  # type: ignore[no-untyped-def]
    """Flush-only audit row inside the intake transaction (shared fate).

    Unlike ``record_audit`` this never commits: the intake pipeline owns
    the single commit (idempotency + intake + audit stay atomic).
    """
    from app.services import audit as audit_service

    audit_service.log_event(
        db,
        business_id=business_id,
        action=action,
        actor_user_id=None,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id(request),
        meta={"channel": "public_website"},
    )


def _attribution_suffix(data: dict) -> str:
    parts = []
    for key in ("landing_page", "referrer", "utm_source", "utm_medium", "utm_campaign"):
        value = (data.get(key) or "").strip()
        if value:
            parts.append(f"{key}={value[:120]}")
    if not parts:
        return ""
    return "[attribution " + " ".join(parts) + "]"

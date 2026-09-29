"""WhatsApp webhook + send APIs (Block 9 step 44; Pre-Prompt-7 foundation).

Routes:
GET  /whatsapp/webhook                 Meta verification (any business token)
GET  /whatsapp/webhook/{business_key}  Meta verification PINNED to one business
POST /whatsapp/webhook                 Inbound + status (business resolved
                                       from credential-bound phone_number_id)
POST /whatsapp/webhook/{business_key}  Inbound PINNED to one business
POST /whatsapp/send                    Staff-authenticated outbound (own
                                       business creds only, via BusinessContext)

Isolation: each business has its OWN Meta app credentials (PRIME_WHATSAPP_*,
NEST_WHATSAPP_*). Verification tokens and HMAC app secrets are checked
per-business; a Prime context can never select Nest credentials. The
``business_slug`` payload field is a DEMO/TEST override only and is IGNORED
in production. No automated sends happen here (Prompt 7 owns automation).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.orm import Session

from app.api import deps
from app.api.v1.endpoints._helpers import map_service_error
from app.core.config import Settings, get_settings
from app.schemas.blocks812 import SendMessageIn
from app.services import communications as comms
from app.services import integration_configs as iconf
from app.services.authorization import AuthenticatedContext
from app.services.messaging import verify_whatsapp_signature
from app.services import public as public_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


# -- verification helpers ------------------------------------------------------


def _all_verify_tokens(settings: Settings) -> list[str]:
    """Every configured verify token (business-scoped first, legacy last)."""
    tokens = [t for t in iconf.verify_tokens(settings).values() if t]
    legacy = (settings.whatsapp_verify_token or "").strip()
    if legacy:
        tokens.append(legacy)
    return tokens


def _check_verify_token(settings: Settings, provided: str) -> bool:
    """True when ``provided`` matches ANY configured verify token."""
    provided = (provided or "").strip()
    if not provided:
        return False
    return any(provided == token for token in _all_verify_tokens(settings) if token)


def _check_verify_token_for_business(
    settings: Settings, business_key: str, provided: str
) -> bool:
    """True when ``provided`` matches ONLY that business's verify token."""
    provided = (provided or "").strip()
    if not provided:
        return False
    expected = iconf.verify_tokens(settings).get(business_key, "")
    return bool(expected) and provided == expected


def _request_id(request: Request | None) -> str:
    if request is None:
        return "-"
    return str(getattr(getattr(request, "state", None), "request_id", "-") or "-")


def _verify_signature_for_business(
    settings: Settings, business_key: str, *, body: bytes, signature: str
) -> bool:
    """HMAC check against ONE business's app secret (fail closed when set).

    When the business has no secret configured this returns True ONLY
    outside production (demo/local webhook testing); production callers must
    fail closed beforehand.
    """
    secret = iconf.app_secrets(settings).get(business_key, "")
    if not secret:
        return not settings.is_production
    return verify_whatsapp_signature(app_secret=secret, body=body, signature=signature)


def _verify_signature_any(settings: Settings, *, body: bytes, signature: str) -> bool:
    """HMAC check against ANY configured app secret (unresolved business).

    Accepts when at least one configured secret (business-scoped or legacy)
    verifies. When NO secret is configured at all, accepts ONLY outside
    production (demo mode); production fails closed beforehand.
    """
    candidates = [s for s in iconf.app_secrets(settings).values() if s]
    legacy = (settings.whatsapp_app_secret or "").strip()
    if legacy:
        candidates.append(legacy)
    if not candidates:
        return not settings.is_production
    return any(
        verify_whatsapp_signature(app_secret=secret, body=body, signature=signature)
        for secret in candidates
    )


def _resolve_business_for_payload(db: Session, settings: Settings, payload: dict):
    """Server-side business resolution for an inbound payload.

    Signal: credential-bound ``metadata.phone_number_id`` values only (each
    mapped through the business-scoped env sets first). Returns the Business
    row or None (safe ack, no records). NEVER trusts ``business_id`` /
    ``phone_number_id`` as authorization — only as a lookup into verified
    registered configuration.
    """
    phone_ids = comms.extract_phone_number_ids(payload)
    for pid in phone_ids:
        try:
            business = comms.resolve_business_for_phone_number_id(
                db, settings, phone_number_id=pid
            )
        except Exception:  # noqa: BLE001 - resolution never breaks the ack
            business = None
        if business is not None:
            return business
    return None


def _process_inbound(
    db: Session, settings: Settings, payload: dict, business=None
) -> None:
    """Persist inbound messages + delivery statuses for ONE business.

    ``business`` None -> safe ack path (nothing created). Commits once;
    any failure rolls back and still acks (webhooks must never 500).
    """
    if not isinstance(payload, dict):
        return
    entries = payload.get("entry", []) or []
    try:
        import time as _time

        for entry in entries:
            # Replay protection: Meta signs `entry[].time` (unix seconds).
            # Entries older than 24h ack without writes (replayed webhook).
            try:
                _ets = entry.get("time", None)
                if _ets is not None:
                    _age = _time.time() - float(_ets)
                    if _age > 86400:
                        logger.warning("whatsapp webhook stale entry acked rid=%s", "-")
                        continue
            except (TypeError, ValueError):
                pass
            for change in entry.get("changes", []) or []:
                value = change.get("value", {}) or {}
                for msg in value.get("messages", []) or []:
                    from_me = msg.get("from", "")
                    text = (
                        ((msg.get("text") or {}).get("body", ""))
                        if isinstance(msg.get("text"), dict)
                        else str(msg.get("body", ""))
                    )
                    mid = str(msg.get("id", ""))
                    if business is not None:
                        comms.record_inbound(
                            db,
                            business_id=business.id,
                            channel="whatsapp",
                            external_id=from_me,
                            sender=from_me,
                            body=text,
                            provider_message_id=mid,
                            raw={"webhook": True},
                        )
                for st in value.get("statuses", []) or []:
                    mid = str(st.get("id", ""))
                    status_value = str(st.get("status", ""))
                    if business is not None and mid:
                        from app.repositories import blocks812 as brepo

                        existing = brepo.get_message_by_provider(
                            db, business_id=business.id, provider_message_id=mid
                        )
                        if existing is not None:
                            existing.status = status_value
                            brepo.record_delivery(
                                db,
                                business_id=business.id,
                                fields={
                                    "message_id": existing.id,
                                    "provider_message_id": mid,
                                    "status": status_value,
                                    "raw": {"webhook": True},
                                },
                            )
        db.commit()
    except Exception:  # noqa: BLE001 - webhook processing must never 500; safe ack
        db.rollback()


# -- verification endpoints ----------------------------------------------------


@router.get("/webhook", summary="Meta webhook verification")
def verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    settings = get_settings()
    if hub_mode == "subscribe" and hub_challenge:
        if _check_verify_token(settings, hub_verify_token):
            return Response(content=hub_challenge, media_type="text/plain")
        # Demo mode (no verify token configured anywhere): echo challenge
        # for local testing. Production fails closed.
        if settings.is_production or _all_verify_tokens(settings):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Webhook verification failed.",
            )
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed."
    )


@router.get("/webhook/{business_key}", summary="Meta webhook verification (pinned)")
def verify_for_business(
    business_key: str,
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
):
    """Verification PINNED to one business (two Meta apps -> two URLs).

    Only ``<business_key>``'s OWN verify token is accepted here, so a Nest
    verification challenge can never succeed against the Prime endpoint.
    """
    key = (business_key or "").strip().lower()
    if key not in iconf.BUSINESS_KEYS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown business webhook."
        )
    settings = get_settings()
    if (
        hub_mode == "subscribe"
        and hub_challenge
        and _check_verify_token_for_business(settings, key, hub_verify_token)
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN, detail="Webhook verification failed."
    )


# -- inbound endpoints ---------------------------------------------------------


@router.post("/webhook", summary="WhatsApp inbound webhook")
async def inbound(request: Request, db: Session = Depends(deps.get_db)):
    settings = get_settings()
    rid = _request_id(request)
    try:
        from app.services import rate_limit as _rl

        _rl.enforce_webhook(settings, request=request, endpoint="whatsapp")
    except HTTPException:
        raise
    except Exception as exc:
        from app.api.v1.endpoints._helpers import map_service_error as _map

        raise _map(exc) from exc
    raw = await request.body()
    if len(raw) > int(getattr(settings, "max_body_bytes", 65536)) * 4:
        # Vendor webhooks are small JSON; oversized bodies ack without parsing.
        logger.warning("whatsapp webhook oversized body rid=%s bytes=%d", rid, len(raw))
        return {"received": True}
    signature = request.headers.get("X-Hub-Signature-256", "")
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - vendor webhooks must never 500 on bad JSON
        return {"received": True}
    if not isinstance(payload, dict):
        return {"received": True}

    business = _resolve_business_for_payload(db, settings, payload)
    if business is not None:
        business_key = iconf.resolve_business_key(business)
        if business_key and iconf.app_secrets(settings).get(business_key):
            if not _verify_signature_for_business(
                settings, business_key, body=raw, signature=signature
            ):
                logger.warning(
                    "whatsapp webhook bad signature business=%s rid=%s",
                    business_key,
                    rid,
                )
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid webhook signature.",
                )
        elif settings.is_production and not (
            iconf.app_secrets(settings).get(business_key or "")
            or (settings.whatsapp_app_secret or "").strip()
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature.",
            )
        else:
            # Unresolved-secret path: require ANY configured secret to verify
            # (or demo mode outside production).
            if not _verify_signature_any(settings, body=raw, signature=signature):
                logger.warning("whatsapp webhook bad signature (any) rid=%s", rid)
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Invalid webhook signature.",
                )
    else:
        # No business resolved: verify against any secret; demo `business_slug`
        # override ONLY outside production (local testing, never trusted).
        if not _verify_signature_any(settings, body=raw, signature=signature):
            logger.warning("whatsapp webhook bad signature (no-biz) rid=%s", rid)
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid webhook signature.",
            )
        slug = str(payload.get("business_slug", "") or "")
        if slug and not settings.is_production:
            try:
                business = public_service.resolve_public_business(db, slug=slug)
            except Exception:  # noqa: BLE001 - unknown slug -> no-business ack
                business = None
        if business is None:
            logger.info("whatsapp webhook unmapped payload acked rid=%s", rid)
    _process_inbound(db, settings, payload, business)
    return {"received": True}


@router.post("/webhook/{business_key}", summary="WhatsApp inbound webhook (pinned)")
async def inbound_for_business(
    business_key: str, request: Request, db: Session = Depends(deps.get_db)
):
    """Inbound PINNED to one business (two Meta apps -> two URLs).

    The URL path (server configuration per Meta app) is the business signal;
    the payload's phone_number_id is cross-checked when the business has a
    configured number, and mismatches ack WITHOUT writes (no cross-tenant
    records on misconfiguration). Signature is checked against ONLY that
    business's app secret.
    """
    key = (business_key or "").strip().lower()
    if key not in iconf.BUSINESS_KEYS:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown business webhook."
        )
    settings = get_settings()
    rid = _request_id(request)
    try:
        from app.services import rate_limit as _rl2

        _rl2.enforce_webhook(settings, request=request, endpoint="whatsapp_pinned")
    except HTTPException:
        raise
    except Exception as exc:
        from app.api.v1.endpoints._helpers import map_service_error as _map2

        raise _map2(exc) from exc
    raw = await request.body()
    if len(raw) > int(getattr(settings, "max_body_bytes", 65536)) * 4:
        logger.warning(
            "whatsapp pinned webhook oversized body business=%s rid=%s", key, rid
        )
        return {"received": True}
    signature = request.headers.get("X-Hub-Signature-256", "")
    if settings.is_production and not iconf.app_secrets(settings).get(key):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature.",
        )
    if not _verify_signature_for_business(settings, key, body=raw, signature=signature):
        logger.warning(
            "whatsapp pinned webhook bad signature business=%s rid=%s", key, rid
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid webhook signature.",
        )
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - vendor webhooks must never 500 on bad JSON
        return {"received": True}
    if not isinstance(payload, dict):
        return {"received": True}

    from app.repositories import businesses as business_repo

    business = business_repo.get_by_slug(db, key)
    if business is None or not business.is_active or business.status != "active":
        return {"received": True}
    # Cross-check: when the business has a configured number and the payload
    # carries phone ids, at least one must match — else ack without writes.
    configured_pid = iconf.resolve_whatsapp_config(
        settings, business
    ).phone_number_id.strip()
    if configured_pid:
        phone_ids = comms.extract_phone_number_ids(payload)
        if phone_ids and configured_pid not in phone_ids:
            logger.warning(
                "whatsapp pinned webhook phone mismatch business=%s rid=%s",
                key,
                rid,
            )
            return {"received": True}
    _process_inbound(db, settings, payload, business)
    return {"received": True}


@router.post("/send", status_code=201, summary="Staff WhatsApp send")
def staff_send(
    payload: SendMessageIn,
    db: Session = Depends(deps.get_db),
    ctx: AuthenticatedContext = Depends(
        deps.require_permission("communications.manage")
    ),
):
    """Staff outbound send using ONLY the staff member's OWN business creds.

    The business comes from the server-side BusinessContext (JWT + DB
    membership) — a forged ``business_id`` in the request can never select
    another business's credentials.
    """
    assert ctx.business is not None
    try:
        msg = comms.send_message(
            db,
            get_settings(),
            business_id=ctx.business.id,
            channel="whatsapp",
            to=payload.to,
            body=payload.body,
            template_code=payload.template_code,
            conversation_id=payload.conversation_id,
            sender=f"staff:{ctx.user.id}",
        )
        db.commit()
        db.refresh(msg)
    except Exception as exc:
        db.rollback()
        raise map_service_error(exc) from exc
    return {"id": msg.id, "status": msg.status, "provider": msg.provider}

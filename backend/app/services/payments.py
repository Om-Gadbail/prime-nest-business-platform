"""Payment service: provider-neutral fee infrastructure (Block 6 step 29).

Core business logic never branches on a provider name. Collection
channels (cash/UPI/card/…) select a small adapter that only normalizes
metadata — money movement for gateways arrives via webhooks (Block 8).
The mock adapter backs tests and local development.

Idempotency: every creation carries an idempotency_key (client-supplied
or generated). Repeating the same key returns the original row — never
a duplicate charge record.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.ops_vocab import PAYMENT_METHODS, PAYMENT_STATUSES, PAYMENT_TRANSITIONS
from app.repositories import payments as payments_repo
from app.services.crm import _clean_text, _validate_enum
from app.services.errors import ConflictError, NotFoundError


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _money(value: object) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("amount must be a valid monetary amount.") from exc
    if amount <= 0:
        raise ValueError("amount must be greater than zero.")
    return amount.quantize(Decimal("0.01"))


# -- provider adapters --------------------------------------------------------
# Adapters normalize channel metadata only. No secrets, no network calls.


class PaymentProvider:
    """Base adapter: validate + normalize creation metadata for a channel."""

    name = "manual"

    def normalize(self, data: dict) -> dict:
        return {"provider": self.name, "provider_ref": ""}


class ManualProvider(PaymentProvider):
    name = "manual"


class CashProvider(PaymentProvider):
    name = "cash"


class UPIProvider(PaymentProvider):
    name = "upi"

    def normalize(self, data: dict) -> dict:
        ref = _clean_text(data.get("provider_ref") or data.get("utr"), max_chars=200)
        return {"provider": self.name, "provider_ref": ref}


class BankTransferProvider(PaymentProvider):
    name = "bank_transfer"

    def normalize(self, data: dict) -> dict:
        ref = _clean_text(data.get("provider_ref"), max_chars=200)
        return {"provider": self.name, "provider_ref": ref}


class CardProvider(PaymentProvider):
    name = "card"


class OnlineProvider(PaymentProvider):
    """Future gateway placeholder: records intent, settles via webhook."""

    name = "online"


class MockProvider(PaymentProvider):
    """Test/local adapter — deterministic, no network, no secrets."""

    name = "mock"


PROVIDERS: dict[str, PaymentProvider] = {
    "manual": ManualProvider(),
    "cash": CashProvider(),
    "upi": UPIProvider(),
    "bank_transfer": BankTransferProvider(),
    "card": CardProvider(),
    "online": OnlineProvider(),
    "mock": MockProvider(),
}


def provider_for(method: str) -> PaymentProvider:
    return PROVIDERS.get(method, ManualProvider())


def _invoice_no(provided: object) -> str:
    """Deterministic invoice reference: caller value or generated INV-... ."""
    clean = _clean_text(provided, max_chars=64)
    if clean:
        return clean
    stamp = _utcnow().strftime("%Y%m%d")
    return f"INV-{stamp}-{uuid.uuid4().hex[:8].upper()}"


# -- service --------------------------------------------------------------------


def get_payment(db: Session, *, business_id: uuid.UUID, payment_id: object):
    payment = payments_repo.get(db, payment_id=payment_id, business_id=business_id)
    if payment is None:
        raise NotFoundError("Payment not found.")
    return payment


def list_payments(
    db: Session,
    *,
    business_id: uuid.UUID,
    member_id=None,
    membership_id=None,
    status=None,
    method=None,
    created_from=None,
    created_to=None,
    limit=None,
    offset=None,
    sort=None,
    direction=None,
):
    from app.repositories.pagination import parse_uuid

    status_clean = (
        _validate_enum(
            status, allowed=PAYMENT_STATUSES, field="status", default="pending"
        )
        if status
        else None
    )
    method_clean = (
        _validate_enum(
            method, allowed=PAYMENT_METHODS, field="method", default="manual"
        )
        if method
        else None
    )
    member_uuid = parse_uuid(member_id) if member_id else None
    if member_id and member_uuid is None:
        raise ValueError("member_id must be a valid UUID.")
    membership_uuid = parse_uuid(membership_id) if membership_id else None
    if membership_id and membership_uuid is None:
        raise ValueError("membership_id must be a valid UUID.")
    return payments_repo.list_scoped(
        db,
        business_id=business_id,
        member_id=member_uuid,
        membership_id=membership_uuid,
        status=status_clean,
        method=method_clean,
        created_from=created_from,
        created_to=created_to,
        limit=limit,
        offset=offset,
        sort=sort,
        direction=direction,
    )


def create_payment(
    db: Session,
    *,
    business_id: uuid.UUID,
    data: dict,
    actor_user_id: uuid.UUID | None = None,
):
    """Create a fee record. Same idempotency_key -> same row (no duplicate)."""
    from app.services import domain_events as events

    idem = (
        _clean_text(data.get("idempotency_key"), max_chars=64)
        or f"pay-{uuid.uuid4().hex}"
    )
    existing = payments_repo.get_by_idem(
        db, business_id=business_id, idempotency_key=idem
    )
    if existing is not None:
        return existing, False

    method = _validate_enum(
        data.get("method", "manual"),
        allowed=PAYMENT_METHODS,
        field="method",
        default="manual",
    )
    adapter = provider_for(method)
    normalized = adapter.normalize(data)

    member_id = _opt_uuid(db, business_id, data.get("member_id"), kind="member")
    membership_id = _opt_uuid(
        db, business_id, data.get("membership_id"), kind="membership"
    )
    customer_id = _opt_uuid(db, business_id, data.get("customer_id"), kind="customer")

    try:
        payment = payments_repo.create(
            db,
            business_id=business_id,
            fields={
                "member_id": member_id,
                "membership_id": membership_id,
                "customer_id": customer_id,
                "amount": _money(data.get("amount")),
                "currency": (
                    _clean_text(data.get("currency", "INR"), max_chars=8).upper()
                    or "INR"
                ),
                "method": method,
                "provider": str(normalized.get("provider") or method)[:64],
                "provider_ref": str(normalized.get("provider_ref") or "")[:200],
                "invoice_no": _invoice_no(data.get("invoice_no")),
                "status": "pending",
                "paid_at": None,
                "due_at": data.get("due_at"),
                "notes": _clean_text(data.get("notes"), max_chars=2000),
                "idempotency_key": idem,
                "created_by_user_id": actor_user_id,
            },
        )
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        winner = payments_repo.get_by_idem(
            db, business_id=business_id, idempotency_key=idem
        )
        if winner is not None:
            return winner, False
        raise ConflictError("Payment conflicts with existing data.") from exc
    events.emit(
        db,
        business_id=business_id,
        event_type="payment.created",
        entity_type="payment",
        entity_id=payment.id,
        actor_user_id=actor_user_id,
        payload={"amount": str(payment.amount), "method": method},
    )
    _sync_membership_payment_state(db, business_id=business_id, payment=payment)
    return payment, True


def set_status(
    db: Session,
    *,
    business_id: uuid.UUID,
    payment_id: object,
    to_status: str,
    actor_user_id: uuid.UUID | None = None,
    settings=None,
):
    """Explicit payment state machine (staff confirm money, never the UI).

    Emits the deterministic payment event; with ``settings``, the growth
    engine routes paid/failed through automation (confirmation/recovery).
    Razorpay is NOT live (demo scope): only the deterministic state
    machine feeds automation — never a provider claim.
    """
    from app.services import domain_events as events

    payment = get_payment(db, business_id=business_id, payment_id=payment_id)
    target = _validate_enum(
        to_status, allowed=PAYMENT_STATUSES, field="status", default="pending"
    )
    current = str(payment.status or "pending").lower()
    if target == current:
        return payment
    if target not in PAYMENT_TRANSITIONS.get(current, frozenset()):
        raise ConflictError(
            f"Cannot move payment from {current.upper()} to {target.upper()}."
        )
    payment.status = target
    if target == "paid":
        payment.paid_at = payment.paid_at or _utcnow()
    payment.updated_at = _utcnow()
    db.flush()
    event_map = {
        "paid": "payment.paid",
        "failed": "payment.failed",
        "overdue": "payment.overdue",
        "refunded": "payment.refunded",
    }
    if target in event_map:
        events.emit(
            db,
            business_id=business_id,
            event_type=event_map[target],
            entity_type="payment",
            entity_id=payment.id,
            actor_user_id=actor_user_id,
            payload={"from": current, "to": target, "amount": str(payment.amount)},
        )
    _sync_membership_payment_state(db, business_id=business_id, payment=payment)
    if (
        settings is not None
        and target in ("paid", "failed")
        and bool(getattr(settings, "automation_enabled", False))
    ):
        try:
            from app.services import growth_engine as _growth

            _growth.on_payment_event(
                db,
                settings,
                business_id=business_id,
                payment=payment,
                status=target,
                actor_user_id=actor_user_id,
            )
        except Exception:  # noqa: BLE001 - automation never breaks payments
            pass
    return payment


def refund_payment(
    db: Session,
    *,
    business_id: uuid.UUID,
    payment_id: object,
    actor_user_id: uuid.UUID | None = None,
    reason: str = "",
):
    """Refund a PAID payment. Requires payments.refund (owner/admin)."""
    reason_clean = _clean_text(reason, max_chars=500)
    if not reason_clean:
        raise ValueError("A refund reason is required.")
    payment = get_payment(db, business_id=business_id, payment_id=payment_id)
    if str(payment.status).lower() != "paid":
        raise ConflictError("Only PAID payments can be refunded.")
    payment.status = "refunded"
    payment.notes = ((payment.notes or "") + f"\nRefund: {reason_clean}").strip()[:2000]
    payment.updated_at = _utcnow()
    db.flush()
    from app.services import domain_events as events

    events.emit(
        db,
        business_id=business_id,
        event_type="payment.refunded",
        entity_type="payment",
        entity_id=payment.id,
        actor_user_id=actor_user_id,
        payload={"amount": str(payment.amount), "reason": reason_clean[:200]},
    )
    _sync_membership_payment_state(db, business_id=business_id, payment=payment)
    return payment


def _sync_membership_payment_state(
    db: Session, *, business_id: uuid.UUID, payment: object
) -> None:
    """Denormalize membership.payment_state from linked payment (best-effort).

    Runs inside the caller's transaction; never raises (a sync failure must
    not roll back the payment itself — reconciliation stays possible).
    """
    try:
        membership_id = getattr(payment, "membership_id", None)
        if membership_id is None:
            return
        from app.repositories import op_memberships as op_membership_repo

        membership = op_membership_repo.get_membership(
            db, membership_id=membership_id, business_id=business_id
        )
        if membership is None:
            return
        mapping = {
            "pending": "pending",
            "partially_paid": "partially_paid",
            "paid": "paid",
            "failed": "failed",
            "cancelled": "cancelled",
            "refunded": "refunded",
            "overdue": "overdue",
        }
        membership.payment_state = mapping.get(
            str(getattr(payment, "status", "pending")), "pending"
        )
        db.flush()
    except Exception:  # noqa: BLE001 - sync is best-effort
        pass


def _opt_uuid(
    db: Session, business_id: uuid.UUID, value: object, *, kind: str
) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        parsed = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{kind}_id must be a valid UUID.") from exc
    # Verify same-business existence (uniform 404, no oracle).
    if kind == "member":
        from app.repositories import members as members_repo

        if members_repo.get(db, member_id=parsed, business_id=business_id) is None:
            raise NotFoundError("Member not found.")
    elif kind == "membership":
        from app.repositories import op_memberships as op_membership_repo

        if (
            op_membership_repo.get_membership(
                db, membership_id=parsed, business_id=business_id
            )
            is None
        ):
            raise NotFoundError("Membership not found.")
    elif kind == "customer":
        from app.repositories import customers as customers_repo

        if (
            customers_repo.get_scoped(db, customer_id=parsed, business_id=business_id)
            is None
        ):
            raise NotFoundError("Customer not found.")
    return parsed


def verify_webhook_signature(*, raw_body: bytes, signature: str, secret: str) -> bool:
    """HMAC-SHA256 verification for provider callbacks (constant-time)."""
    import hashlib
    import hmac

    if not secret or not signature:
        return False
    digest = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(digest, signature.strip().lower())


def handle_webhook(
    db: Session, *, business_id: uuid.UUID, provider: str, payload: dict, settings=None
) -> dict:
    """Provider callback entrypoint: authenticated, idempotent, audited.

    Contract (provider-neutral):
    - payload must carry ``idempotency_key`` matching the original payment,
      plus ``status`` (paid|failed), ``amount`` and ``currency``.
    - amount/currency are verified against the trusted internal payment row;
      mismatches raise without mutating (no partial credit, no activation).
    - duplicate delivery returns the existing payment (no double credit).
    - membership entitlement flips only via the verified ``paid`` transition
      inside the same transaction.
    """
    idem = _clean_text(payload.get("idempotency_key"), max_chars=64)
    if not idem:
        raise ValueError("Webhook payload must carry an idempotency_key.")
    status_raw = _clean_text(payload.get("status"), max_chars=32).lower()
    if status_raw not in ("paid", "failed"):
        raise ValueError("Webhook status must be 'paid' or 'failed'.")
    from app.services import domain_events as events

    payment = payments_repo.get_by_idem(
        db, business_id=business_id, idempotency_key=idem
    )
    if payment is None:
        raise NotFoundError("Unknown payment for webhook idempotency_key.")
    # Verify amount/currency against the trusted row when supplied.
    if payload.get("amount") not in (None, ""):
        try:
            claimed = Decimal(str(payload.get("amount"))).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError, TypeError) as exc:
            raise ValueError("Webhook amount must be a valid monetary amount.") from exc
        if claimed != Decimal(str(payment.amount)).quantize(Decimal("0.01")):
            raise ConflictError("Webhook amount does not match payment record.")
    if payload.get("currency") not in (None, ""):
        claimed_cur = _clean_text(payload.get("currency"), max_chars=8).upper()
        if claimed_cur != str(payment.currency or "").upper():
            raise ConflictError("Webhook currency does not match payment record.")
    current = str(payment.status or "pending").lower()
    if current == status_raw or (current == "paid" and status_raw == "paid"):
        # Replay / duplicate delivery: safe no-op, report existing truth.
        return {
            "status": str(payment.status),
            "provider": provider,
            "idempotency_key": idem,
            "payment_id": str(payment.id),
            "duplicate": True,
        }
    if status_raw == "paid":
        payment = set_status(
            db,
            business_id=business_id,
            payment_id=payment.id,
            to_status="paid",
            settings=settings,
        )
    else:
        payment = set_status(
            db,
            business_id=business_id,
            payment_id=payment.id,
            to_status="failed",
            settings=settings,
        )
    events.emit(
        db,
        business_id=business_id,
        event_type="payment.recorded",
        entity_type="payment",
        entity_id=payment.id,
        payload={"provider": str(provider)[:64], "webhook": "verified"},
    )
    return {
        "status": str(payment.status),
        "provider": provider,
        "idempotency_key": idem,
        "payment_id": str(payment.id),
        "duplicate": False,
    }

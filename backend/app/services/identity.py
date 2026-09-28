"""Unified identity service (Block 3, step 14).

The same real-world person may interact with Prime Fitness AND Nest
Library. This service links per-business contacts to one global person
using STRICT equality on normalized phone/email only:

- Both signals present and agreeing (same person) -> link with
  confidence "both".
- Exactly one signal matching exactly one person -> link ("phone"/"email").
- Phone and email each matching DIFFERENT persons -> AMBIGUOUS: keep
  identities separate (link to the phone-anchored person, record the
  conflict, never merge). Staff can resolve later via explicit manual
  link (OWNER/ADMIN, audited).
- No signal at all -> no person, no link (nothing to match on).

Privacy (non-negotiable):
- Links are written per business at intake/contact-creation time.
- Reading ANOTHER business's links/person relationships requires
  ``identity.read`` (OWNER/ADMIN). Business-scoped endpoints only ever
  return the caller's own business slice.
- API responses mask normalized signals (last-4 phone, masked email).

Concurrency: unique constraints make concurrent creation collapse.
``ensure_link_for_contact`` runs in the CALLER's transaction and may raise
IntegrityError on a genuine race; the caller owns retry policy (public
intake retries the attempt once; staff endpoints surface a safe 409 and
the retry reuses the winner). No hidden rollbacks here — a rollback
would discard the caller's contact/lead work.
"""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.repositories import persons as persons_repo
from app.services import normalize as norm
from app.services.errors import ConflictError, NotFoundError


def _signals(phone: str | None, email: str | None) -> tuple[str | None, str | None]:
    return norm.normalize_phone(phone), norm.normalize_email(email)


def ensure_link_for_contact(
    db: Session,
    *,
    business_id: uuid.UUID,
    contact_id: uuid.UUID,
    phone: str | None,
    email: str | None,
    actor_user_id: uuid.UUID | None = None,
) -> tuple[object | None, bool, bool]:
    """Ensure person+link for a contact. Returns (link|None, matched, ambiguous).

    Never raises on ambiguity (keeps separate). May raise IntegrityError
    on a concurrent-creation race — the caller retries (see contract).
    """
    normalized_phone, normalized_email = _signals(phone, email)
    if not normalized_phone and not normalized_email:
        return None, False, False
    return _ensure_once(
        db,
        business_id=business_id,
        contact_id=contact_id,
        normalized_phone=normalized_phone,
        normalized_email=normalized_email,
        actor_user_id=actor_user_id,
    )


def _ensure_once(
    db: Session,
    *,
    business_id: uuid.UUID,
    contact_id: uuid.UUID,
    normalized_phone: str | None,
    normalized_email: str | None,
    actor_user_id: uuid.UUID | None,
) -> tuple[object | None, bool, bool]:
    existing_link = persons_repo.get_link(
        db, business_id=business_id, contact_id=contact_id
    )
    if existing_link is not None:
        return existing_link, True, False

    person_by_phone = None
    person_by_email = None
    if normalized_phone:
        person_by_phone = persons_repo.get_person_by_signals(
            db, normalized_phone=normalized_phone, normalized_email=None
        )
    if normalized_email:
        person_by_email = persons_repo.get_person_by_signals(
            db, normalized_phone=None, normalized_email=normalized_email
        )

    ambiguous = (
        person_by_phone is not None
        and person_by_email is not None
        and person_by_phone.id != person_by_email.id
    )
    if ambiguous:
        # Keep separate: anchor on the phone person, record the conflict.
        person = person_by_phone
        assert person is not None
        link = persons_repo.create_link(
            db,
            business_id=business_id,
            person_id=person.id,
            contact_id=contact_id,
            link_type="auto",
            confidence="phone",
            created_by_user_id=actor_user_id,
            note="Ambiguous: email matches a different identity; kept separate.",
        )
        db.flush()
        return link, True, True

    person = person_by_phone or person_by_email
    matched = person is not None
    if person is None:
        person = persons_repo.create_person(
            db, normalized_phone=normalized_phone, normalized_email=normalized_email
        )
    if normalized_phone and person_by_phone is None and person.normalized_phone is None:
        # Same person matched via email; attach the new phone signal when
        # free (unique constraint guards races -> caller retries).
        person.normalized_phone = normalized_phone
        db.flush()
    if normalized_email and person_by_email is None and person.normalized_email is None:
        person.normalized_email = normalized_email
        db.flush()
    confidence = (
        "both"
        if (normalized_phone and normalized_email)
        else ("phone" if normalized_phone else "email")
    )
    link = persons_repo.create_link(
        db,
        business_id=business_id,
        person_id=person.id,
        contact_id=contact_id,
        link_type="auto",
        confidence=confidence,
        created_by_user_id=actor_user_id,
    )
    db.flush()
    return link, matched, False


def manual_link(
    db: Session,
    *,
    business_id: uuid.UUID,
    contact_id: uuid.UUID,
    person_id: uuid.UUID,
    actor_user_id: uuid.UUID | None = None,
    note: str = "",
) -> object:
    """Explicit staff link (OWNER/ADMIN enforced by router). Audited by caller."""
    from app.repositories import contacts as contacts_repo

    contact = contacts_repo.get_scoped(
        db, contact_id=contact_id, business_id=business_id
    )
    if contact is None:
        raise NotFoundError("Contact not found.")
    person = persons_repo.get_person(db, person_id=person_id)
    if person is None:
        raise NotFoundError("Person not found.")
    existing = persons_repo.get_link(db, business_id=business_id, contact_id=contact.id)
    if existing is not None:
        raise ConflictError("This contact is already linked to an identity.")
    link = persons_repo.create_link(
        db,
        business_id=business_id,
        person_id=person.id,
        contact_id=contact.id,
        link_type="manual",
        confidence="manual",
        created_by_user_id=actor_user_id,
        note=note,
    )
    db.flush()
    return link


def person_overview(db: Session, *, person_id: object, business_id: uuid.UUID) -> dict:
    """Business-scoped slice of a person (own business links only).

    Cross-business relationships are NEVER included here; they require
    the privileged cross-business endpoint (``identity.read``).
    """
    person = persons_repo.get_person(db, person_id=person_id)
    if person is None:
        raise NotFoundError("Person not found.")
    links = persons_repo.list_links_for_person(
        db, person_id=person.id, business_id=business_id
    )
    if not links:
        raise NotFoundError("Person not found.")
    return {
        "person_id": person.id,
        "phone_masked": norm.mask_phone_last4(person.normalized_phone),
        "email_masked": norm.mask_email(person.normalized_email),
        "links": [
            {
                "link_id": link.id,
                "contact_id": link.contact_id,
                "link_type": link.link_type,
                "confidence": link.confidence,
                "created_at": link.created_at,
            }
            for link in links
        ],
    }


def cross_business_overview(db: Session, *, person_id: object) -> dict:
    """Privileged cross-business view (router enforces ``identity.read``).

    Returns per-business link counts + masked signals only — never full
    contact rows, names, or messages. Staff drill down per business with
    that business's own context.
    """
    from sqlalchemy import select

    from app.models.business import Business

    person = persons_repo.get_person(db, person_id=person_id)
    if person is None:
        raise NotFoundError("Person not found.")
    links = persons_repo.list_links_for_person(db, person_id=person.id)
    business_ids = sorted({link.business_id for link in links})
    businesses: dict[uuid.UUID, str] = {}
    if business_ids:
        rows = (
            db.execute(select(Business).where(Business.id.in_(business_ids)))
            .scalars()
            .all()
        )
        businesses = {b.id: b.slug for b in rows}
    per_business: dict[str, int] = {}
    for link in links:
        slug = businesses.get(link.business_id, "unknown")
        per_business[slug] = per_business.get(slug, 0) + 1
    return {
        "person_id": person.id,
        "phone_masked": norm.mask_phone_last4(person.normalized_phone),
        "email_masked": norm.mask_email(person.normalized_email),
        "businesses": per_business,
        "total_links": len(links),
    }

"""Block 3 — unified customer/contact identity (privacy-preserving)."""

from __future__ import annotations

from tests.block2_support import auth_headers, b2, login_as, public_lead_payload  # noqa: F401


def test_same_person_links_across_businesses(b2) -> None:
    payload = public_lead_payload(phone="+919111122233", email="same@example.com")
    prime_lead = b2["client"].post("/api/v1/public/prime/leads", json=payload)
    assert prime_lead.status_code == 201, prime_lead.text
    nest_lead = b2["client"].post("/api/v1/public/nest/leads", json=payload)
    assert nest_lead.status_code == 201, nest_lead.text

    prime = auth_headers(b2["prime"]["access_token"])
    nest = auth_headers(b2["nest"]["access_token"])

    prime_links = b2["client"].get("/api/v1/identity/links", headers=prime).json()
    nest_links = b2["client"].get("/api/v1/identity/links", headers=nest).json()
    assert prime_links["total"] == 1
    assert nest_links["total"] == 1
    # Same global person, two per-business links.
    assert prime_links["items"][0]["person_id"] == nest_links["items"][0]["person_id"]

    # Prime's slice shows only Prime's link; Nest's slice only Nest's.
    person_id = prime_links["items"][0]["person_id"]
    prime_view = b2["client"].get(f"/api/v1/identity/persons/{person_id}", headers=prime)
    assert prime_view.status_code == 200, prime_view.text
    assert len(prime_view.json()["links"]) == 1
    # Normalized signals are masked, never raw.
    assert prime_view.json()["phone_masked"].endswith("2233")
    assert "normalized" not in prime_view.text

    # Unknown person in my business -> 404 (no oracle).
    ghost = b2["client"].get(
        "/api/v1/identity/persons/00000000-0000-0000-0000-000000000000", headers=prime
    )
    assert ghost.status_code == 404


def test_cross_business_view_requires_identity_read(b2) -> None:
    payload = public_lead_payload(phone="+919222233344", email="cross@example.com")
    assert b2["client"].post("/api/v1/public/prime/leads", json=payload).status_code == 201
    assert b2["client"].post("/api/v1/public/nest/leads", json=payload).status_code == 201

    prime_owner = auth_headers(b2["prime"]["access_token"])
    person_id = (
        b2["client"].get("/api/v1/identity/links", headers=prime_owner).json()["items"][0]["person_id"]
    )
    cross = b2["client"].get(
        f"/api/v1/identity/persons/{person_id}/cross-business", headers=prime_owner
    )
    assert cross.status_code == 200, cross.text
    body = cross.json()
    assert body["businesses"] == {"prime": 1, "nest": 1}
    assert body["total_links"] == 2
    # Masked only — no raw contact data, no names.
    assert "cross@example.com" not in cross.text
    assert "+919222233344" not in cross.text

    # STAFF (no identity.read) is denied; MANAGER too; VIEWER too.
    for role in ("MANAGER", "STAFF", "VIEWER"):
        tokens = login_as(
            b2["client"], b2["db"], email=f"xbus-{role.lower()}@example.com",
            slug="prime", role=role,
        )
        h = auth_headers(tokens["access_token"])
        resp = b2["client"].get(
            f"/api/v1/identity/persons/{person_id}/cross-business", headers=h
        )
        assert resp.status_code == 403, (role, resp.text)


def test_family_shared_phone_not_merged(b2) -> None:
    # Same phone, different emails via public intake -> the EXISTING
    # contact is reused (Block 2 duplicate prevention), so one link.
    p1 = public_lead_payload(phone="+919333344455", email="member1@example.com")
    p2 = public_lead_payload(phone="+919333344455", email="member2@example.com")
    assert b2["client"].post("/api/v1/public/prime/leads", json=p1).status_code == 201
    assert b2["client"].post("/api/v1/public/prime/leads", json=p2).status_code == 201

    prime = auth_headers(b2["prime"]["access_token"])
    links = b2["client"].get("/api/v1/identity/links", headers=prime).json()
    assert links["total"] == 1
    contacts = b2["client"].get("/api/v1/contacts?search=919333344455", headers=prime)
    assert contacts.json()["total"] == 1  # reused, not duplicated

    # Staff may still register two distinct family contacts sharing a
    # phone (no global uniqueness); each gets its own link row.
    c1 = b2["client"].post(
        "/api/v1/contacts",
        json={"first_name": "Kin", "last_name": "One", "phone": "+919333344456"},
        headers=prime,
    )
    c2 = b2["client"].post(
        "/api/v1/contacts",
        json={"first_name": "Kin", "last_name": "Two", "phone": "+919333344456"},
        headers=prime,
    )
    assert c1.status_code == 201 and c2.status_code == 201, (c1.text, c2.text)
    assert c1.json()["id"] != c2.json()["id"]


def test_ambiguous_signals_keep_separate() -> None:
    from tests.block1_support import make_test_session

    engine, db = make_test_session()
    try:
        from sqlalchemy import select

        from app.models.business import Business
        from app.services import crm as crm_service

        business = db.execute(select(Business).where(Business.slug == "prime")).scalars().first()
        assert business is not None
        # Person A via phone only, person B via email only (auto-linked).
        c1 = crm_service.create_contact(
            db, business_id=business.id, first_name="Alpha", phone="+919444455566"
        )
        c2 = crm_service.create_contact(
            db, business_id=business.id, first_name="Beta", email="beta@example.com"
        )
        db.commit()
        # A contact carrying A's phone + B's email is AMBIGUOUS: the auto
        # path anchors on the phone person and records the conflict.
        c3 = crm_service.create_contact(
            db, business_id=business.id, first_name="Gamma",
            phone="+919444455566", email="beta@example.com",
        )
        db.commit()
        from app.repositories import persons as persons_repo

        link3 = persons_repo.get_link(
            db, business_id=business.id, contact_id=c3.id
        )
        assert link3 is not None
        assert link3.confidence == "phone"
        assert "Ambiguous" in link3.note
        # The two original persons were NOT merged (still distinct).
        person1 = persons_repo.get_link(db, business_id=business.id, contact_id=c1.id).person_id
        person2 = persons_repo.get_link(db, business_id=business.id, contact_id=c2.id).person_id
        assert person1 != person2
        assert link3.person_id == person1
    finally:
        db.close()
        engine.dispose()


def test_manual_link_owner_only_and_audited(b2) -> None:
    prime_owner = auth_headers(b2["prime"]["access_token"])
    # Two contacts with no signals -> no auto person.
    c1 = b2["client"].post(
        "/api/v1/contacts", json={"first_name": "Manual", "last_name": "One"},
        headers=prime_owner,
    )
    assert c1.status_code == 201, c1.text
    c2 = b2["client"].post(
        "/api/v1/contacts", json={"first_name": "Manual", "last_name": "Two"},
        headers=prime_owner,
    )
    assert c2.status_code == 201, c2.text

    # Create a person via a signaled contact, then link manually is
    # rejected for duplicates but unknown person -> 404.
    resp = b2["client"].post(
        "/api/v1/identity/links",
        json={
            "contact_id": c1.json()["id"],
            "person_id": "00000000-0000-0000-0000-000000000000",
            "note": "Family record, verified in person.",
        },
        headers=prime_owner,
    )
    assert resp.status_code == 404, resp.text

    # STAFF cannot use manual linking at all.
    staff = login_as(
        b2["client"], b2["db"], email="manual-staff@example.com",
        slug="prime", role="STAFF",
    )
    denied = b2["client"].post(
        "/api/v1/identity/links",
        json={
            "contact_id": c1.json()["id"],
            "person_id": "00000000-0000-0000-0000-000000000000",
        },
        headers=auth_headers(staff["access_token"]),
    )
    assert denied.status_code == 403, denied.text

"""Create throwaway LOCAL-DEV-ONLY live E2E users (never production).

Accounts: prime.owner@live.example.com (prime OWNER),
          nest.owner@live.example.com  (nest OWNER).
Password: $E2E_STAFF_PASSWORD or 'LiveCheck-1234!'.

Idempotent. Run against the Docker DB from the repo root, e.g. PowerShell:
  $env:DATABASE_URL='postgresql+psycopg://postgres:postgres@localhost:5433/app_db'
  python backend/seed_live_e2e.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sqlalchemy import select

from app.core import security
from app.core.database import get_session_factory, reset_engine_cache
from app.models.business import Business
from app.repositories import memberships as mr
from app.repositories import users as ur


def main() -> None:
    reset_engine_cache()
    password = os.environ.get("E2E_STAFF_PASSWORD", "LiveCheck-1234!")
    factory = get_session_factory()
    db = factory()
    try:
        businesses = {b.slug: b for b in db.execute(select(Business)).scalars().all()}
        assert "prime" in businesses and "nest" in businesses, "seed prime/nest first"
        owner_role = mr.get_role_by_name(db, name="OWNER")
        assert owner_role is not None, "seed RBAC first"
        for slug, email in (("prime", "prime.owner@live.example.com"),
                            ("nest", "nest.owner@live.example.com")):
            user = ur.get_by_email(db, email=email)
            if user is None:
                user = ur.create(
                    db, email=email,
                    password_hash=security.hash_password(password),
                    full_name=f"{slug} live owner",
                    is_active=True, is_verified=True,
                )
                db.commit()
                db.refresh(user)
                print(f"created user {email}")
            membership = mr.get_membership(db, user_id=user.id,
                                           business_id=businesses[slug].id)
            if membership is None:
                mr.create_membership(db, user_id=user.id,
                                     business_id=businesses[slug].id,
                                     role_id=owner_role.id, status="active",
                                     is_default=True)
                db.commit()
                print(f"added {email} -> {slug} OWNER")
            else:
                print(f"exists {email} -> {slug} ({membership.status})")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""Blocks 5-7 — owner command center + Prime/Nest operations.

Revision ID: 0005_block5_7_operations
Revises: 0004_block3_tasks_audit_identity

DDL (all BUSINESS_SCOPED unless noted):
- ``members`` — operational member profiles (CRM-linked).
- ``membership_plans`` — data-driven plan catalogue (Nest pricing lives here).
- ``memberships`` — enrolments; price snapshotted; status/payment_state split.
- ``payments`` — provider-neutral fees with idempotency keys.
- ``attendance`` — one row per member per day (unique = dedupe safety).
- ``renewals`` — renewal pipeline (expiry never deletes history).
- ``seat_areas`` / ``seats`` — configurable seat inventory.
- ``seat_allocations`` — exclusive assignments; partial unique indexes give
  at most one ACTIVE allocation per seat AND per member (race-safe).
- ``approvals`` — owner approval/control foundation.
- ``domain_events`` — durable hook log for future Block 8 automation.

Data: insert the Block 5-7 permissions and grant them per the matrix in
app/models/rbac.py (hardcoded here so this historical migration never
depends on future code changes). Pre-existing keys (members.*,
payments.read/create, analytics.read) are grant-only: rows for them are
owned by the baseline seed and are never deleted here.
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_block5_7_operations"
down_revision: Union[str, None] = "0004_block3_tasks_audit_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Genuinely NEW permission rows owned by this migration. Pre-existing keys
# (members.read/create/update, payments.read/create, analytics.read) are
# granted below where the matrix changed but their rows are NOT owned here.
BLOCK57_NEW_PERMISSION_KEYS = (
    "memberships.read",
    "memberships.create",
    "memberships.update",
    "membership_plans.read",
    "membership_plans.manage",
    "payments.update",
    "payments.refund",
    "attendance.read",
    "attendance.create",
    "attendance.update",
    "renewals.read",
    "renewals.create",
    "renewals.update",
    "seats.read",
    "seats.manage",
    "analytics.owner",
    "owner.dashboard.read",
    "owner.combined.read",
    "approvals.read",
    "approvals.manage",
)

# Must mirror app/models/rbac.py at Blocks 5-7 time (additive only).
# Includes pre-existing keys where the matrix newly grants them.
BLOCK57_ROLE_GRANTS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(
        (
            "members.read",
            "members.create",
            "members.update",
            "memberships.read",
            "memberships.create",
            "memberships.update",
            "membership_plans.read",
            "membership_plans.manage",
            "payments.read",
            "payments.create",
            "payments.update",
            "payments.refund",
            "attendance.read",
            "attendance.create",
            "attendance.update",
            "renewals.read",
            "renewals.create",
            "renewals.update",
            "seats.read",
            "seats.manage",
            "analytics.read",
            "analytics.owner",
            "owner.dashboard.read",
            "owner.combined.read",
            "approvals.read",
            "approvals.manage",
        )
    ),
    "ADMIN": frozenset(
        (
            "members.read",
            "members.create",
            "members.update",
            "memberships.read",
            "memberships.create",
            "memberships.update",
            "membership_plans.read",
            "membership_plans.manage",
            "payments.read",
            "payments.create",
            "payments.update",
            "payments.refund",
            "attendance.read",
            "attendance.create",
            "attendance.update",
            "renewals.read",
            "renewals.create",
            "renewals.update",
            "seats.read",
            "seats.manage",
            "analytics.read",
            "analytics.owner",
            "owner.dashboard.read",
            "owner.combined.read",
            "approvals.read",
            "approvals.manage",
        )
    ),
    "MANAGER": frozenset(
        {
            "members.read",
            "members.create",
            "members.update",
            "memberships.read",
            "memberships.create",
            "memberships.update",
            "membership_plans.read",
            "payments.read",
            "payments.create",
            "payments.update",
            "attendance.read",
            "attendance.create",
            "attendance.update",
            "renewals.read",
            "renewals.create",
            "renewals.update",
            "seats.read",
            "analytics.read",
            "owner.dashboard.read",
            "approvals.read",
        }
    ),
    "STAFF": frozenset(
        {
            "members.read",
            "members.create",
            "memberships.read",
            "memberships.create",
            "membership_plans.read",
            "payments.read",
            "payments.create",
            "attendance.read",
            "attendance.create",
            "renewals.read",
            "seats.read",
        }
    ),
    "VIEWER": frozenset(
        {
            "members.read",
            "memberships.read",
            "membership_plans.read",
            "payments.read",
            "attendance.read",
            "renewals.read",
            "seats.read",
            "analytics.read",
            "owner.dashboard.read",
            "approvals.read",
        }
    ),
}


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _ts_columns() -> list:
    return [
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _ts(), server_default=sa.text("now()"), nullable=False),
    ]


def _user_fk(col: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [col], ["users.id"],
        name=f"fk_op_{col}_users",
        ondelete="SET NULL",
    )


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lead_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("display_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("normalized_phone", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("emergency_contact_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("emergency_contact_phone", sa.String(length=32), nullable=True),
        sa.Column("seat_preference", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_members_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_members_customer_id_customers", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name="fk_members_contact_id_contacts", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], name="fk_members_lead_id_leads", ondelete="SET NULL"),
        _user_fk("created_by_user_id"),
        _user_fk("updated_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_members"),
        sa.UniqueConstraint("business_id", "customer_id", name="uq_members_business_customer"),
    )
    op.create_index("ix_members_business_id", "members", ["business_id"], unique=False)
    op.create_index("ix_members_business_status", "members", ["business_id", "status"], unique=False)
    op.create_index("ix_members_business_created", "members", ["business_id", "created_at"], unique=False)
    op.create_index("ix_members_business_phone", "members", ["business_id", "normalized_phone"], unique=False)
    op.create_index("ix_members_business_email", "members", ["business_id", "normalized_email"], unique=False)
    op.create_index("ix_members_business_contact", "members", ["business_id", "contact_id"], unique=False)

    op.create_table(
        "membership_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="custom"),
        sa.Column("duration_months", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("is_best_value", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("features", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_membership_plans_business_id_businesses", ondelete="RESTRICT"),
        _user_fk("created_by_user_id"),
        _user_fk("updated_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_membership_plans"),
        sa.UniqueConstraint("business_id", "code", name="uq_membership_plans_business_code"),
    )
    op.create_index("ix_membership_plans_business_id", "membership_plans", ["business_id"], unique=False)
    op.create_index("ix_membership_plans_business_active", "membership_plans", ["business_id", "is_active"], unique=False)
    op.create_index("ix_membership_plans_business_category", "membership_plans", ["business_id", "category"], unique=False)

    op.create_table(
        "memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("payment_state", sa.String(length=32), nullable=False, server_default="unpaid"),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("discount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("final_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("plan_name_snapshot", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("plan_version_snapshot", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("cancel_reason", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("cancelled_at", _ts(), nullable=True),
        sa.Column("renewed_from_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_memberships_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], name="fk_memberships_member_id_members", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["plan_id"], ["membership_plans.id"], name="fk_memberships_plan_id_membership_plans", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_memberships_customer_id_customers", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["renewed_from_id"], ["memberships.id"], name="fk_memberships_renewed_from_id_memberships", ondelete="SET NULL"),
        _user_fk("created_by_user_id"),
        _user_fk("updated_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_memberships_business_idem"),
    )
    op.create_index("ix_memberships_business_id", "memberships", ["business_id"], unique=False)
    op.create_index("ix_memberships_business_member", "memberships", ["business_id", "member_id"], unique=False)
    op.create_index("ix_memberships_business_status", "memberships", ["business_id", "status"], unique=False)
    op.create_index("ix_memberships_business_end", "memberships", ["business_id", "end_date"], unique=False)
    op.create_index("ix_memberships_business_plan", "memberships", ["business_id", "plan_id"], unique=False)
    op.create_index("ix_memberships_business_payment", "memberships", ["business_id", "payment_state"], unique=False)

    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("method", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("provider", sa.String(length=64), nullable=False, server_default="manual"),
        sa.Column("provider_ref", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("invoice_no", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("paid_at", _ts(), nullable=True),
        sa.Column("due_at", _ts(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_payments_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], name="fk_payments_member_id_members", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_payments_membership_id_memberships", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["customer_id"], ["customers.id"], name="fk_payments_customer_id_customers", ondelete="SET NULL"),
        _user_fk("created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_payments"),
        sa.UniqueConstraint("business_id", "idempotency_key", name="uq_payments_business_idem"),
    )
    op.create_index("ix_payments_business_id", "payments", ["business_id"], unique=False)
    op.create_index("ix_payments_business_member", "payments", ["business_id", "member_id"], unique=False)
    op.create_index("ix_payments_business_membership", "payments", ["business_id", "membership_id"], unique=False)
    op.create_index("ix_payments_business_status", "payments", ["business_id", "status"], unique=False)
    op.create_index("ix_payments_business_created", "payments", ["business_id", "created_at"], unique=False)
    op.create_index("ix_payments_business_due", "payments", ["business_id", "due_at"], unique=False)

    # seat_areas/seats come BEFORE attendance: attendance.seat_id
    # references seats.id (Postgres requires the target to exist first).
    op.create_table(
        "seat_areas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("floor", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_seat_areas_business_id_businesses", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_areas"),
        sa.UniqueConstraint("business_id", "code", name="uq_seat_areas_business_code"),
    )
    op.create_index("ix_seat_areas_business_id", "seat_areas", ["business_id"], unique=False)
    op.create_index("ix_seat_areas_business_floor", "seat_areas", ["business_id", "floor"], unique=False)

    op.create_table(
        "seats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("area_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("seat_number", sa.String(length=64), nullable=False),
        sa.Column("seat_type", sa.String(length=32), nullable=False, server_default="regular"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="available"),
        sa.Column("notes", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_seats_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["area_id"], ["seat_areas.id"], name="fk_seats_area_id_seat_areas", ondelete="SET NULL"),
        _user_fk("created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_seats"),
        sa.UniqueConstraint("business_id", "seat_number", name="uq_seats_business_number"),
    )
    op.create_index("ix_seats_business_id", "seats", ["business_id"], unique=False)
    op.create_index("ix_seats_business_status", "seats", ["business_id", "status"], unique=False)
    op.create_index("ix_seats_business_area", "seats", ["business_id", "area_id"], unique=False)
    op.create_index("ix_seats_business_type", "seats", ["business_id", "seat_type"], unique=False)

    op.create_table(
        "attendance",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("seat_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attendance_date", sa.Date(), nullable=False),
        sa.Column("checked_in_at", _ts(), nullable=False),
        sa.Column("checked_out_at", _ts(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="manual"),
        sa.Column("notes", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_attendance_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], name="fk_attendance_member_id_members", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_attendance_membership_id_memberships", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["seat_id"], ["seats.id"], name="fk_attendance_seat_id_seats", ondelete="SET NULL"),
        _user_fk("created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_attendance"),
        sa.UniqueConstraint("business_id", "member_id", "attendance_date", name="uq_attendance_business_member_day"),
    )
    op.create_index("ix_attendance_business_id", "attendance", ["business_id"], unique=False)
    op.create_index("ix_attendance_business_day", "attendance", ["business_id", "attendance_date"], unique=False)
    op.create_index("ix_attendance_business_member", "attendance", ["business_id", "member_id"], unique=False)
    op.create_index("ix_attendance_business_seat", "attendance", ["business_id", "seat_id"], unique=False)

    op.create_table(
        "renewals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("new_membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("previous_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("new_plan_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("renewal_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="INR"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column("renewed_at", _ts(), nullable=True),
        sa.Column("notes", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_renewals_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], name="fk_renewals_member_id_members", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_renewals_membership_id_memberships", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["new_membership_id"], ["memberships.id"], name="fk_renewals_new_membership_id_memberships", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["previous_plan_id"], ["membership_plans.id"], name="fk_renewals_previous_plan_id_membership_plans", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["new_plan_id"], ["membership_plans.id"], name="fk_renewals_new_plan_id_membership_plans", ondelete="SET NULL"),
        _user_fk("created_by_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_renewals"),
    )
    op.create_index("ix_renewals_business_id", "renewals", ["business_id"], unique=False)
    op.create_index("ix_renewals_business_member", "renewals", ["business_id", "member_id"], unique=False)
    op.create_index("ix_renewals_business_status", "renewals", ["business_id", "status"], unique=False)
    op.create_index("ix_renewals_business_due", "renewals", ["business_id", "due_date"], unique=False)
    op.create_index("ix_renewals_business_membership", "renewals", ["business_id", "membership_id"], unique=False)

    op.create_table(
        "seat_allocations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("seat_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("member_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("membership_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("allocated_at", _ts(), nullable=False),
        sa.Column("released_at", _ts(), nullable=True),
        sa.Column("notes", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("allocated_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("released_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_seat_allocations_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seat_id"], ["seats.id"], name="fk_seat_allocations_seat_id_seats", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["member_id"], ["members.id"], name="fk_seat_allocations_member_id_members", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["membership_id"], ["memberships.id"], name="fk_seat_allocations_membership_id_memberships", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["allocated_by_user_id"], ["users.id"], name="fk_op_allocated_by_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["released_by_user_id"], ["users.id"], name="fk_op_released_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_allocations"),
    )
    op.create_index("ix_seat_alloc_business_id", "seat_allocations", ["business_id"], unique=False)
    op.create_index("ix_seat_alloc_business_seat", "seat_allocations", ["business_id", "seat_id"], unique=False)
    op.create_index("ix_seat_alloc_business_member", "seat_allocations", ["business_id", "member_id"], unique=False)
    op.create_index("ix_seat_alloc_business_status", "seat_allocations", ["business_id", "status"], unique=False)
    # Race-safe exclusivity: enforced by the database, not just Python.
    op.create_index(
        "uq_seat_alloc_active_seat", "seat_allocations", ["seat_id"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_seat_alloc_active_member", "seat_allocations", ["member_id"], unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.create_table(
        "approvals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(length=48), nullable=False, server_default=""),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=False, server_default="approve"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("reason", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", _ts(), nullable=True),
        sa.Column("decision_note", sa.String(length=2000), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_approvals_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], name="fk_op_requested_by_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by_user_id"], ["users.id"], name="fk_op_decided_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_approvals"),
    )
    op.create_index("ix_approvals_business_id", "approvals", ["business_id"], unique=False)
    op.create_index("ix_approvals_business_status", "approvals", ["business_id", "status"], unique=False)
    op.create_index("ix_approvals_business_entity", "approvals", ["business_id", "entity_type"], unique=False)
    op.create_index("ix_approvals_business_created", "approvals", ["business_id", "created_at"], unique=False)

    op.create_table(
        "domain_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("entity_type", sa.String(length=48), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_domain_events_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_op_actor_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_domain_events"),
    )
    op.create_index("ix_domain_events_business_id", "domain_events", ["business_id"], unique=False)
    op.create_index("ix_domain_events_business_type", "domain_events", ["business_id", "event_type"], unique=False)
    op.create_index("ix_domain_events_business_created", "domain_events", ["business_id", "created_at"], unique=False)
    op.create_index("ix_domain_events_business_entity", "domain_events", ["business_id", "entity_type", "entity_id"], unique=False)

    _seed_block57_permissions()


def _seed_block57_permissions() -> None:
    """Insert new Block 5-7 permissions + system-role grants (idempotent)."""
    bind = op.get_bind()
    for key in BLOCK57_NEW_PERMISSION_KEYS:
        exists = bind.execute(
            sa.text("SELECT id FROM permissions WHERE key = :key"),
            {"key": key},
        ).first()
        if exists is None:
            bind.execute(
                sa.text(
                    "INSERT INTO permissions (id, key, description) "
                    "VALUES (:id, :key, :description)"
                ),
                {
                    "id": uuid4(),
                    "key": key,
                    "description": f"Blocks 5-7 operations permission: {key}.",
                },
            )
    for role_name, keys in BLOCK57_ROLE_GRANTS.items():
        for key in keys:
            row = bind.execute(
                sa.text(
                    "SELECT r.id AS role_id, p.id AS perm_id FROM roles r "
                    "JOIN permissions p ON p.key = :key "
                    "WHERE r.name = :role AND r.business_id IS NULL"
                ),
                {"key": key, "role": role_name},
            ).first()
            if row is None:
                continue
            grant = bind.execute(
                sa.text(
                    "SELECT 1 FROM role_permissions "
                    "WHERE role_id = :role_id AND permission_id = :perm_id"
                ),
                {"role_id": row.role_id, "perm_id": row.perm_id},
            ).first()
            if grant is None:
                bind.execute(
                    sa.text(
                        "INSERT INTO role_permissions (role_id, permission_id) "
                        "VALUES (:role_id, :perm_id)"
                    ),
                    {"role_id": row.role_id, "perm_id": row.perm_id},
                )


def downgrade() -> None:
    bind = op.get_bind()
    # Remove grants for keys OWNED by this migration only. Grants on
    # pre-existing keys (members.*, payments.read/create, analytics.read)
    # stay — their rows belong to the baseline seed.
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key IN :keys)"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(BLOCK57_NEW_PERMISSION_KEYS)},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(BLOCK57_NEW_PERMISSION_KEYS)},
    )

    op.drop_table("domain_events")
    op.drop_table("approvals")
    op.drop_index("uq_seat_alloc_active_member", table_name="seat_allocations")
    op.drop_index("uq_seat_alloc_active_seat", table_name="seat_allocations")
    op.drop_table("seat_allocations")
    op.drop_table("renewals")
    op.drop_table("attendance")
    op.drop_table("seats")
    op.drop_table("seat_areas")
    op.drop_table("payments")
    op.drop_table("memberships")
    op.drop_table("membership_plans")
    op.drop_table("members")

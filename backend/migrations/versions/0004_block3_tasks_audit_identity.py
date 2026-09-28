"""Block 3/4 — business connections, tasks, audit, unified identity.

Revision ID: 0004_block3_tasks_audit_identity
Revises: 0003_block2_leads_crm

DDL:
- ``tasks`` (business-scoped staff work items).
- ``audit_events`` (append-only business-scoped activity log).
- ``persons`` (global identity: normalized signals only, no PII).
- ``identity_links`` (per-business person <-> contact join).
- ``leads``: routing columns (routed_by, routing_reason, routed_at).

Data: insert the Block 3/4 permissions and grant them to the system
roles per the matrix in app/models/rbac.py (hardcoded here so this
historical migration never depends on future code changes).
"""

from typing import Sequence, Union
from uuid import uuid4

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_block3_tasks_audit_identity"
down_revision: Union[str, None] = "0003_block2_leads_crm"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Must mirror app/models/rbac.py at Block 3/4 time (additive only).
BLOCK34_PERMISSION_KEYS = (
    "leads.transfer",
    "identity.read",
    "tasks.read",
    "tasks.create",
    "tasks.update",
    "audit.read",
    "dashboard.read",
)

BLOCK34_ROLE_GRANTS: dict[str, frozenset[str]] = {
    "OWNER": frozenset(BLOCK34_PERMISSION_KEYS),
    "ADMIN": frozenset(BLOCK34_PERMISSION_KEYS),
    "MANAGER": frozenset(
        {"tasks.read", "tasks.create", "tasks.update", "audit.read", "dashboard.read"}
    ),
    "STAFF": frozenset(
        {"tasks.read", "tasks.create", "tasks.update", "audit.read", "dashboard.read"}
    ),
    "VIEWER": frozenset({"tasks.read", "dashboard.read"}),
}


def _ts() -> sa.DateTime:
    return sa.DateTime(timezone=True)


def _ts_columns() -> list:
    return [
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", _ts(), server_default=sa.text("now()"), nullable=False),
    ]


def upgrade() -> None:
    op.create_table(
        "tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=2000), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("assigned_to_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("due_at", _ts(), nullable=True),
        sa.Column("completed_at", _ts(), nullable=True),
        sa.Column("related_entity_type", sa.String(length=48), nullable=True),
        sa.Column("related_entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_tasks_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["assigned_to_user_id"], ["users.id"], name="fk_tasks_assigned_to_user_id_users", ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_tasks_created_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
    )
    op.create_index("ix_tasks_business_id", "tasks", ["business_id"], unique=False)
    op.create_index("ix_tasks_business_status", "tasks", ["business_id", "status"], unique=False)
    op.create_index("ix_tasks_business_assignee", "tasks", ["business_id", "assigned_to_user_id"], unique=False)
    op.create_index("ix_tasks_business_due", "tasks", ["business_id", "due_at"], unique=False)
    op.create_index("ix_tasks_business_created", "tasks", ["business_id", "created_at"], unique=False)
    op.create_index("ix_tasks_business_creator", "tasks", ["business_id", "created_by_user_id"], unique=False)

    op.create_table(
        "audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("entity_type", sa.String(length=48), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=False, server_default="success"),
        sa.Column("request_id", sa.String(length=64), nullable=False, server_default="-"),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=300), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", _ts(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_audit_events_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"], name="fk_audit_events_actor_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
    )
    op.create_index("ix_audit_events_business_id", "audit_events", ["business_id"], unique=False)
    op.create_index("ix_audit_events_business_created", "audit_events", ["business_id", "created_at"], unique=False)
    op.create_index("ix_audit_events_business_actor", "audit_events", ["business_id", "actor_user_id"], unique=False)
    op.create_index(
        "ix_audit_events_business_entity",
        "audit_events",
        ["business_id", "entity_type", "entity_id"],
        unique=False,
    )
    op.create_index("ix_audit_events_business_action", "audit_events", ["business_id", "action"], unique=False)

    op.create_table(
        "persons",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("normalized_phone", sa.String(length=32), nullable=True),
        sa.Column("normalized_email", sa.String(length=320), nullable=True),
        *_ts_columns(),
        sa.PrimaryKeyConstraint("id", name="pk_persons"),
        sa.UniqueConstraint("normalized_phone", name="uq_persons_normalized_phone"),
        sa.UniqueConstraint("normalized_email", name="uq_persons_normalized_email"),
    )
    op.create_index("ix_persons_phone", "persons", ["normalized_phone"], unique=False)
    op.create_index("ix_persons_email", "persons", ["normalized_email"], unique=False)

    op.create_table(
        "identity_links",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("person_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("link_type", sa.String(length=16), nullable=False, server_default="auto"),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=False, server_default=""),
        *_ts_columns(),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_identity_links_business_id_businesses", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["person_id"], ["persons.id"], name="fk_identity_links_person_id_persons", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["contact_id"], ["contacts.id"], name="fk_identity_links_contact_id_contacts", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], name="fk_identity_links_created_by_user_id_users", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_identity_links"),
        sa.UniqueConstraint("business_id", "contact_id", name="uq_identity_links_business_contact"),
    )
    op.create_index("ix_identity_links_business_id", "identity_links", ["business_id"], unique=False)
    op.create_index("ix_identity_links_person", "identity_links", ["person_id"], unique=False)
    op.create_index(
        "ix_identity_links_business_person",
        "identity_links",
        ["business_id", "person_id"],
        unique=False,
    )

    op.add_column("leads", sa.Column("routed_by", sa.String(length=64), nullable=False, server_default="system"))
    op.add_column("leads", sa.Column("routing_reason", sa.String(length=500), nullable=False, server_default=""))
    op.add_column("leads", sa.Column("routed_at", _ts(), nullable=True))

    _seed_block34_permissions()


def _seed_block34_permissions() -> None:
    """Insert Block 3/4 permissions + system-role grants (idempotent)."""
    bind = op.get_bind()
    for key in BLOCK34_PERMISSION_KEYS:
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
                    "description": f"Block 3/4 operations permission: {key}.",
                },
            )
    for role_name, keys in BLOCK34_ROLE_GRANTS.items():
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
    bind.execute(
        sa.text(
            "DELETE FROM role_permissions WHERE permission_id IN "
            "(SELECT id FROM permissions WHERE key IN :keys)"
        ).bindparams(sa.bindparam("keys", expanding=True)),
        {"keys": list(BLOCK34_PERMISSION_KEYS)},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE key IN :keys").bindparams(
            sa.bindparam("keys", expanding=True)
        ),
        {"keys": list(BLOCK34_PERMISSION_KEYS)},
    )

    op.drop_column("leads", "routed_at")
    op.drop_column("leads", "routing_reason")
    op.drop_column("leads", "routed_by")
    op.drop_table("identity_links")
    op.drop_table("persons")
    op.drop_table("audit_events")
    op.drop_table("tasks")

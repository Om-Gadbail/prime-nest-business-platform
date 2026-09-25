"""Identity + multi-tenancy foundation: businesses, users, RBAC, memberships, settings, sessions.

Revision ID: 0002_identity_multitenancy
Revises: 0001_baseline
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_identity_multitenancy"
down_revision: Union[str, None] = "0001_baseline"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "businesses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("business_type", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("timezone", sa.String(length=64), nullable=True, server_default="UTC"),
        sa.Column("currency", sa.String(length=8), nullable=True),
        sa.Column("locale", sa.String(length=16), nullable=True),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("whatsapp", sa.String(length=32), nullable=True),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("address_line_1", sa.String(length=255), nullable=True),
        sa.Column("address_line_2", sa.String(length=255), nullable=True),
        sa.Column("city", sa.String(length=128), nullable=True),
        sa.Column("state", sa.String(length=128), nullable=True),
        sa.Column("postal_code", sa.String(length=32), nullable=True),
        sa.Column("country", sa.String(length=64), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_businesses"),
        sa.UniqueConstraint("slug", name="uq_businesses_slug"),
    )
    op.create_index("ix_businesses_slug", "businesses", ["slug"], unique=False)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("phone", sa.String(length=32), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("is_verified", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=False)

    op.create_table(
        "roles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("display_name", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("is_system", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_roles_business_id_businesses", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_roles"),
        sa.UniqueConstraint("business_id", "name", name="uq_roles_business_id_name"),
    )
    op.create_index("ix_roles_business_id", "roles", ["business_id"], unique=False)
    op.create_index("ix_roles_name", "roles", ["name"], unique=False)
    # System-role name uniqueness (business_id IS NULL): Postgres partial index.
    op.create_index(
        "uq_roles_system_name",
        "roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("business_id IS NULL"),
    )

    op.create_table(
        "permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_permissions"),
        sa.UniqueConstraint("key", name="uq_permissions_key"),
    )
    op.create_index("ix_permissions_key", "permissions", ["key"], unique=False)

    op.create_table(
        "role_permissions",
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("permission_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_role_permissions_role_id_roles", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["permission_id"], ["permissions.id"], name="fk_role_permissions_permission_id_permissions", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("role_id", "permission_id", name="pk_role_permissions"),
    )

    op.create_table(
        "business_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_business_memberships_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_business_memberships_business_id_businesses", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["role_id"], ["roles.id"], name="fk_business_memberships_role_id_roles", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_business_memberships"),
        sa.UniqueConstraint("user_id", "business_id", name="uq_business_memberships_user_business"),
    )
    op.create_index("ix_business_memberships_user_id", "business_memberships", ["user_id"], unique=False)
    op.create_index("ix_business_memberships_business_id", "business_memberships", ["business_id"], unique=False)
    op.create_index("ix_business_memberships_role_id", "business_memberships", ["role_id"], unique=False)

    op.create_table(
        "business_settings",
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("branding", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("contact", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("address", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("hours", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("localization", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("operational", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_business_settings_business_id_businesses", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("business_id", name="pk_business_settings"),
    )

    op.create_table(
        "auth_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("refresh_token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.String(length=500), nullable=True),
        sa.Column("ip_address", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_auth_sessions_user_id_users", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], name="fk_auth_sessions_business_id_businesses", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_auth_sessions"),
        sa.UniqueConstraint("refresh_token_hash", name="uq_auth_sessions_refresh_token_hash"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"], unique=False)
    op.create_index("ix_auth_sessions_business_id", "auth_sessions", ["business_id"], unique=False)
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"], unique=False)
    op.create_index("ix_auth_sessions_revoked_at", "auth_sessions", ["revoked_at"], unique=False)


def downgrade() -> None:
    op.drop_table("auth_sessions")
    op.drop_table("business_settings")
    op.drop_table("business_memberships")
    op.drop_table("role_permissions")
    op.drop_table("permissions")
    op.drop_index("uq_roles_system_name", table_name="roles")
    op.drop_index("ix_roles_name", table_name="roles")
    op.drop_index("ix_roles_business_id", table_name="roles")
    op.drop_table("roles")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_businesses_slug", table_name="businesses")
    op.drop_table("businesses")

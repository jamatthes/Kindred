"""foundation — identity, sessions, trip, settings, bare family tables.

Revision ID: 0001
Revises:
Create Date: 2026-08-11

Creates everything milestone M0 needs:

* ``users`` / ``user_settings`` — identity, with a **functional** unique index on
  ``lower(username)`` so usernames are unique case-insensitively without requiring the
  ``citext`` extension.
* ``sessions`` / ``login_attempts`` — the two PROPOSED ADDITIONs from
  ``plan/features/foundation/design.md``, now recorded in ``plan/architecture.md``.
* ``trips``, ``settings`` — the single active trip and key/value platform config.
* ``families`` / ``family_members`` — created **bare** so ``require_member`` can resolve
  membership. The ``families`` feature owns them from here and adds its own columns,
  unique indexes and endpoints.

``gen_random_uuid()`` is built into Postgres 13+, so no extension is created.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def _timestamps() -> list[sa.Column]:
    """Fresh Column objects each call — a Column instance may belong to only one table."""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    ]


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=120), nullable=False),
        sa.Column("must_change_password", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("theme_pref", sa.String(length=16), server_default="system", nullable=False),
        sa.Column("locale", sa.String(length=16), server_default="en-GB", nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive uniqueness. Login looks users up by lower(username), which this serves.
    op.create_index(
        "ix_users_username_lower",
        "users",
        [sa.literal_column("lower(username)")],
        unique=True,
    )

    op.create_table(
        "user_settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "live_location_enabled", sa.Boolean(), server_default="false", nullable=False
        ),
        sa.Column("push_enabled", sa.Boolean(), server_default="false", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Exactly one settings row per user.
        sa.UniqueConstraint("user_id", name="uq_user_settings_user_id"),
    )

    op.create_table(
        "sessions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_sessions_token_hash"),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"], unique=False)
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"], unique=False)

    op.create_table(
        "login_attempts",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("succeeded", sa.Boolean(), server_default="false", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_login_attempts_created_at", "login_attempts", ["created_at"])
    # The two composite indexes serve the trailing-60s failure counts by username and by ip.
    op.create_index(
        "ix_login_attempts_username_created_at", "login_attempts", ["username", "created_at"]
    )
    op.create_index("ix_login_attempts_ip_created_at", "login_attempts", ["ip", "created_at"])

    op.create_table(
        "trips",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("stage", sa.String(length=16), server_default="planning", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "timezone", sa.String(length=64), server_default="Europe/London", nullable=False
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key", name="uq_settings_key"),
    )

    # --- bare tables owned by the `families` feature from here on -----------------------
    op.create_table(
        "families",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("color", sa.SmallInteger(), nullable=True),
        sa.Column("home_address", sa.Text(), nullable=True),
        sa.Column("home_lat", sa.Float(), nullable=True),
        sa.Column("home_lng", sa.Float(), nullable=True),
        sa.Column("home_geocoded_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_families_trip_id", "families", ["trip_id"], unique=False)

    op.create_table(
        "family_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="member", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_family_members_family_id", "family_members", ["family_id"], unique=False)
    op.create_index("ix_family_members_user_id", "family_members", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_family_members_user_id", table_name="family_members")
    op.drop_index("ix_family_members_family_id", table_name="family_members")
    op.drop_table("family_members")
    op.drop_index("ix_families_trip_id", table_name="families")
    op.drop_table("families")
    op.drop_table("settings")
    op.drop_table("trips")
    op.drop_index("ix_login_attempts_ip_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_username_created_at", table_name="login_attempts")
    op.drop_index("ix_login_attempts_created_at", table_name="login_attempts")
    op.drop_table("login_attempts")
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
    op.drop_table("user_settings")
    op.drop_index("ix_users_username_lower", table_name="users")
    op.drop_table("users")

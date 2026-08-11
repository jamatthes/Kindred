"""families — columns, constraints, and the invites/attachments tables.

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-12

Everything here is listed as an approved addition in ``plan/architecture.md``.

Two deviations from `plan/features/families/tasks.md`, both recorded as NOTEs in that
feature's `design.md`:

* `invites` and `attachments` are **created**, not altered. `architecture.md` lists both in
  the schema, but foundation's `0001` only created the tables it actually used, so neither
  exists yet. The columns tasks.md says to "add" to `invites` are therefore part of the
  create, and there is no plaintext `token` column to replace — the table is born hashed.
* `families.color` becomes NOT NULL. A family without a colour slot cannot be drawn on the
  map, and `(trip_id, color)` unique would not constrain nulls anyway. The table is empty at
  this point (foundation seeds no family), so there is nothing to backfill.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GEOCODE_STATUSES = ("pending", "ok", "not_found", "error")

#: `family_members.role`, revised 2026-08-11: `admin` renamed to `head`, `spouse` added.
FAMILY_ROLES = ("head", "spouse", "member")


def upgrade() -> None:
    # --- attachments -------------------------------------------------------------------
    # Referenced by users.avatar_attachment_id below, so it has to exist first.
    op.create_table(
        "attachments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("uploader_id", sa.UUID(), nullable=True),
        sa.Column("path", sa.Text(), nullable=False),
        # The small rendition. Avatars emit two sizes (256 and 64); other subjects may emit
        # one, so this is nullable rather than a second required file.
        sa.Column("thumb_path", sa.Text(), nullable=True),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attachments_subject", "attachments", ["subject_type", "subject_id"], unique=False
    )

    # --- users -------------------------------------------------------------------------
    # first_name arrives nullable so existing rows can be backfilled, then is tightened.
    op.add_column("users", sa.Column("first_name", sa.String(length=80), nullable=True))
    op.add_column(
        "users",
        sa.Column("last_name", sa.String(length=80), server_default="", nullable=False),
    )
    op.add_column("users", sa.Column("avatar_attachment_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_users_avatar_attachment_id",
        "users",
        "attachments",
        ["avatar_attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )

    # Split the existing display_name: everything before the first space is the first name,
    # the remainder the last. For the seeded admin ("Admin") that gives first="Admin",
    # last="", which is exactly the single-name case the initials rule already handles.
    op.execute(
        """
        UPDATE users
           SET first_name = NULLIF(split_part(display_name, ' ', 1), ''),
               last_name  = COALESCE(
                   NULLIF(substr(display_name, strpos(display_name, ' ') + 1), display_name),
                   ''
               )
        """
    )
    # Anything still null had an empty display_name; fall back to the username.
    op.execute("UPDATE users SET first_name = username WHERE first_name IS NULL")
    op.alter_column("users", "first_name", nullable=False)

    # --- families ----------------------------------------------------------------------
    op.add_column("families", sa.Column("home_locality", sa.Text(), nullable=True))
    op.add_column(
        "families",
        sa.Column(
            "geocode_status", sa.String(length=16), server_default="pending", nullable=False
        ),
    )
    op.add_column("families", sa.Column("geocode_error", sa.Text(), nullable=True))
    op.add_column(
        "families",
        sa.Column(
            "location_sharing_allowed", sa.Boolean(), server_default="true", nullable=False
        ),
    )
    op.add_column(
        "families",
        sa.Column(
            "member_location_default", sa.Boolean(), server_default="false", nullable=False
        ),
    )
    op.create_check_constraint(
        "ck_families_geocode_status",
        "families",
        "geocode_status IN " + str(GEOCODE_STATUSES),
    )

    # A family with no colour cannot be drawn; the table is empty here, so no backfill.
    op.alter_column("families", "color", existing_type=sa.SmallInteger(), nullable=False)
    op.create_check_constraint(
        "ck_families_color_range", "families", "color BETWEEN 1 AND 8"
    )

    # Name uniqueness is case-insensitive per trip — "The Smiths" and "the smiths" are the
    # same family to a human, so they must be to the database.
    op.create_index(
        "uq_families_trip_name_lower",
        "families",
        ["trip_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_index("uq_families_trip_color", "families", ["trip_id", "color"], unique=True)

    # --- family_members ----------------------------------------------------------------
    op.add_column(
        "family_members",
        sa.Column(
            "location_sharing_allowed", sa.Boolean(), server_default="true", nullable=False
        ),
    )
    # One family per user (plan/overview.md). Enforced here rather than only in application
    # code, because a second membership row would corrupt every permission check.
    op.drop_index("ix_family_members_user_id", table_name="family_members")
    op.create_index("uq_family_members_user_id", "family_members", ["user_id"], unique=True)

    # `admin` becomes `head`, and `spouse` joins it (roles revised 2026-08-11). Foundation
    # writes no membership rows, so this UPDATE is a no-op on a real install; it is here so
    # the migration is correct for a database that already has data.
    op.execute("UPDATE family_members SET role = 'head' WHERE role = 'admin'")
    op.alter_column("family_members", "role", server_default="member")
    op.create_check_constraint(
        "ck_family_members_role", "family_members", "role IN " + str(FAMILY_ROLES)
    )
    # **Exactly one head per family.** Two heads plus the spouse asymmetry — neither able to
    # act on the other — is a deadlock nobody inside the family can unpick, and zero heads can
    # only be repaired by an organiser. A partial unique index says so in the one place that
    # cannot be bypassed.
    op.create_index(
        "uq_family_members_one_head",
        "family_members",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("role = 'head'"),
    )

    # --- trip_organisers ---------------------------------------------------------------
    # The owner delegates every cross-family power except the power to delegate (FM-17).
    # Created here because this feature's permission dependencies read it from the first
    # route; the endpoints that write it belong to `admin-console`.
    op.create_table(
        "trip_organisers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # Nullable: deleting the account that made a grant must not take the grant with it.
        sa.Column("granted_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        # No `updated_at`. The row's existence *is* the grant, so there is nothing to mutate
        # — revoking is a delete.
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_organisers_trip_user"),
    )
    op.create_index("ix_trip_organisers_trip_id", "trip_organisers", ["trip_id"], unique=False)

    # --- invites -----------------------------------------------------------------------
    op.create_table(
        "invites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        # Null means "this invite creates a new family" (FM-6).
        sa.Column("family_id", sa.UUID(), nullable=True),
        # Only the sha256 is stored, exactly as foundation does for session cookies. The raw
        # token is shown once at creation and is not retrievable afterwards.
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("used_by", sa.UUID(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        # A deleted family must not take its invites' rows with it silently — the accept
        # route reports `invite_family_missing`, which needs the row to still be there.
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_invites_token_hash"),
    )
    op.create_index("ix_invites_family_id", "invites", ["family_id"], unique=False)
    op.create_index("ix_invites_expires_at", "invites", ["expires_at"], unique=False)
    op.create_index("ix_invites_trip_id", "invites", ["trip_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_trip_organisers_trip_id", table_name="trip_organisers")
    op.drop_table("trip_organisers")

    op.drop_index("ix_invites_trip_id", table_name="invites")
    op.drop_index("ix_invites_expires_at", table_name="invites")
    op.drop_index("ix_invites_family_id", table_name="invites")
    op.drop_table("invites")

    op.drop_index("uq_family_members_one_head", table_name="family_members")
    op.drop_constraint("ck_family_members_role", "family_members", type_="check")
    op.execute("UPDATE family_members SET role = 'admin' WHERE role IN ('head', 'spouse')")
    op.drop_index("uq_family_members_user_id", table_name="family_members")
    op.create_index("ix_family_members_user_id", "family_members", ["user_id"], unique=False)
    op.drop_column("family_members", "location_sharing_allowed")

    op.drop_index("uq_families_trip_color", table_name="families")
    op.drop_index("uq_families_trip_name_lower", table_name="families")
    op.drop_constraint("ck_families_color_range", "families", type_="check")
    op.alter_column("families", "color", existing_type=sa.SmallInteger(), nullable=True)
    op.drop_constraint("ck_families_geocode_status", "families", type_="check")
    op.drop_column("families", "member_location_default")
    op.drop_column("families", "location_sharing_allowed")
    op.drop_column("families", "geocode_error")
    op.drop_column("families", "geocode_status")
    op.drop_column("families", "home_locality")

    op.drop_constraint("fk_users_avatar_attachment_id", "users", type_="foreignkey")
    op.drop_column("users", "avatar_attachment_id")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")

    op.drop_index("ix_attachments_subject", table_name="attachments")
    op.drop_table("attachments")

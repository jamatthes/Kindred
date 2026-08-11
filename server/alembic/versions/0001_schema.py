"""Kindred — the whole schema, in one revision.

Revision ID: 0001
Revises:
Create Date: 2026-08-11

**This is the only migration, and pre-launch it is edited in place** (`CLAUDE.md` >
Migrations). Nothing is deployed yet, so a chain of incremental revisions would be an audit
trail of decisions nobody made in production — and reading four files to learn the shape of
one table is a worse way to onboard than reading one. The never-edit-an-applied-migration
discipline begins at the first production deploy, at which point this file freezes and
`0002` starts the real chain.

Consolidated here from what were `0001_foundation`, `0002_families` and `0003_invite_mode`.
The design decisions each of those recorded are kept as comments beside the columns they
justify, because that is the part worth preserving.

Contents:

* **Identity** — `users`, `user_settings`, `sessions`, `login_attempts`
* **Trip + configuration** — `trips`, `settings`, `trip_organisers`,
  `trip_category_settings`, `trip_stage_transitions`
* **Families** — `families`, `family_members`, `invites`
* **Platform** — `attachments`

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

#: `families.geocode_status`. `pending` means never attempted, which is why a family whose
#: address has been cleared goes back to it rather than to `not_found`.
GEOCODE_STATUSES = ("pending", "ok", "not_found", "error")

#: `family_members.role`. Family-level roles, independent of the trip-level owner/organiser
#: pair — the owner is also an ordinary head, spouse or member of their own family.
FAMILY_ROLES = ("head", "spouse", "member")

#: `invites.mode`. Stated rather than inferred from a null `family_id`; see the column.
INVITE_MODES = ("join", "create_family")

#: The design palette defines eight slots (`--family-1…8`).
#: The curated palette (2026-08-11: grown from 8 to 24; slots 1-8 keep their original hex
#: values in both themes). The 25th family on a trip gets a free-choice colour wheel instead
#: of a slot — see `families.color_custom` below and `ck_families_color_xor`.
MAX_COLOR_SLOTS = 24

#: `trip_category_settings.category`. Five fixed kinds of thing a group votes on; `poll`
#: governs every poll, because the mode is per category rather than per poll
#: (`plan/features/admin-console/requirements.md`, the NOTE on AC-5).
VOTING_CATEGORIES = ("poll", "region", "accommodation", "activity", "meal")

#: `trip_category_settings.voting_mode`.
VOTING_MODES = ("score", "thumbs")

#: `trip_stage_transitions.direction`. Stored rather than derived: reading a row should not
#: require knowing the stage machine to tell a correction from a normal advance.
STAGE_DIRECTIONS = ("forward", "backward")


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
    # --- identity ------------------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        # Collected at registration. The map badge is initials and its hover label is a full
        # name; neither can be derived reliably from one free-text field.
        sa.Column("first_name", sa.String(length=80), nullable=False),
        # Not null, empty when absent — nullable-by-emptiness, so the initials rule is total.
        # A mononym gets a one-letter badge, which is correct rather than a degraded case.
        sa.Column("last_name", sa.String(length=80), server_default="", nullable=False),
        # Seeded to "{first} {last}".strip() at registration, separately editable after.
        sa.Column("display_name", sa.String(length=120), nullable=False),
        # The profile picture. The FK is added after `attachments` exists — the two tables
        # reference each other, so one side has to come second.
        sa.Column("avatar_attachment_id", sa.UUID(), nullable=True),
        sa.Column("must_change_password", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("theme_pref", sa.String(length=16), server_default="system", nullable=False),
        sa.Column("locale", sa.String(length=16), server_default="en-GB", nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), server_default="false", nullable=False),
        # Null until the first successful login. `admin-console` AC-6 asks "has this person
        # ever got in?", which `created_at` cannot answer — an invited account that was never
        # used looks identical to one used daily without this.
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id"),
    )
    # Case-insensitive uniqueness, functional so it does not need the `citext` extension.
    # Login looks users up by lower(username), which this serves.
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
        # **Consent**, written only by the member themselves. No admin writes it for anyone
        # else; the single exception is the one-time seed from
        # `families.member_location_default` when a membership row is created.
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
        # sha256 of the opaque cookie value; the raw value is never stored, so a database
        # dump does not hand over live sessions.
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("ip", postgresql.INET(), nullable=True),
        # The mutable column, touched at most once a minute. No `updated_at`.
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
        # Lowercased, and recorded even when no such user exists.
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("ip", postgresql.INET(), nullable=True),
        sa.Column("succeeded", sa.Boolean(), server_default="false", nullable=False),
        # Append-only rows, so no `updated_at`.
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

    # --- trip and configuration ------------------------------------------------------------
    op.create_table(
        "trips",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("stage", sa.String(length=16), server_default="planning", nullable=False),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        # The **owner** — the one role that can appoint organisers.
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

    # The owner delegates every cross-family power except the power to delegate. Created by
    # `families` because its permission dependencies read it; the endpoints that write it
    # belong to `admin-console`.
    op.create_table(
        "trip_organisers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        # Nullable: deleting the account that made a grant must not take the grant with it.
        sa.Column("granted_by", sa.UUID(), nullable=True),
        # No `updated_at`. The row's existence *is* the grant — revoking is a delete.
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("trip_id", "user_id", name="uq_trip_organisers_trip_user"),
    )
    op.create_index("ix_trip_organisers_trip_id", "trip_organisers", ["trip_id"], unique=False)

    # How each kind of thing is voted on. One row per (trip, category), all five seeded when
    # the trip is created, so no read ever has to invent a default and no UI ever renders a
    # blank control. `admin-console` owns the endpoints.
    op.create_table(
        "trip_category_settings",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("voting_mode", sa.String(length=16), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "category IN " + str(VOTING_CATEGORIES),
            name="ck_trip_category_settings_category",
        ),
        sa.CheckConstraint(
            "voting_mode IN " + str(VOTING_MODES),
            name="ck_trip_category_settings_voting_mode",
        ),
        # The rule that makes the self-healing read safe: a missing row can be inserted
        # without risking a second one racing in beside it.
        sa.UniqueConstraint(
            "trip_id", "category", name="uq_trip_category_settings_trip_category"
        ),
    )
    op.create_index(
        "ix_trip_category_settings_trip_id", "trip_category_settings", ["trip_id"], unique=False
    )

    # The one audit trail in v1 (`admin-console` design.md > out of scope): who moved the
    # trip between stages, when, and in which direction. Append-only — nothing updates or
    # deletes a row here, which is why it has a `created_at` and no `updated_at`.
    op.create_table(
        "trip_stage_transitions",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("from_stage", sa.String(length=16), nullable=False),
        sa.Column("to_stage", sa.String(length=16), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=False),
        # Nullable: removing an account must not delete the record that it changed the stage.
        # The history is about the trip, not about the person still existing.
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "direction IN " + str(STAGE_DIRECTIONS),
            name="ck_trip_stage_transitions_direction",
        ),
    )
    # The history is always read newest-first for one trip; this is that query.
    op.create_index(
        "ix_trip_stage_transitions_trip_created",
        "trip_stage_transitions",
        ["trip_id", "created_at"],
        unique=False,
    )

    # --- families ----------------------------------------------------------------------------
    op.create_table(
        "families",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        # A smallint token slot, not a hex colour, so the design system can retune the palette
        # without a data migration. Nullable since 2026-08-11: once all 24 slots on a trip are
        # claimed, a family gets a free-choice hex in `color_custom` instead — exactly one of
        # the two is ever set, enforced by `ck_families_color_xor` below.
        sa.Column("color", sa.SmallInteger(), nullable=True),
        # The overflow colour wheel's value (`#RRGGBB`), set only when the palette was full at
        # pick time. Escapes the curated palette's tuning/distinguishability guarantees by
        # design — see `plan/features/families/design.md` > Family colour palette.
        sa.Column("color_custom", sa.String(length=7), nullable=True),
        sa.Column("home_address", sa.Text(), nullable=True),
        sa.Column("home_lat", sa.Float(), nullable=True),
        sa.Column("home_lng", sa.Float(), nullable=True),
        sa.Column("home_geocoded_at", sa.DateTime(timezone=True), nullable=True),
        # The coarse town from the geocode — what members of *other* families are shown, so
        # the full street address never has to leave the server for them.
        sa.Column("home_locality", sa.Text(), nullable=True),
        sa.Column(
            "geocode_status", sa.String(length=16), server_default="pending", nullable=False
        ),
        sa.Column("geocode_error", sa.Text(), nullable=True),
        # The family's master map switch. Read on every map query; turning it off removes the
        # whole family without touching anyone's own setting.
        sa.Column(
            "location_sharing_allowed", sa.Boolean(), server_default="true", nullable=False
        ),
        # Copied into `user_settings.live_location_enabled` exactly once, when a member joins.
        sa.Column(
            "member_location_default", sa.Boolean(), server_default="false", nullable=False
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            f"geocode_status IN {GEOCODE_STATUSES}", name="ck_families_geocode_status"
        ),
        sa.CheckConstraint(
            f"color IS NULL OR color BETWEEN 1 AND {MAX_COLOR_SLOTS}",
            name="ck_families_color_range",
        ),
        # Exactly one of the palette slot or the overflow custom hex is ever set — the row
        # can never claim both a slot and a wheel colour, or neither.
        sa.CheckConstraint(
            "(color IS NOT NULL AND color_custom IS NULL) OR "
            "(color IS NULL AND color_custom IS NOT NULL)",
            name="ck_families_color_xor",
        ),
    )
    op.create_index("ix_families_trip_id", "families", ["trip_id"], unique=False)
    # Name uniqueness is case-insensitive per trip — "The Smiths" and "the smiths" are the
    # same family to a human, so they must be to the database.
    op.create_index(
        "uq_families_trip_name_lower",
        "families",
        ["trip_id", sa.literal_column("lower(name)")],
        unique=True,
    )
    op.create_index("uq_families_trip_color", "families", ["trip_id", "color"], unique=True)

    op.create_table(
        "family_members",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", sa.String(length=16), server_default="member", nullable=False),
        # The per-member map switch — the head or spouse's decision that this person is not
        # shown, independent of whether that person has consented. It lives here rather than
        # on `users` because it is a fact about a person's place in a family, and must
        # disappear along with the membership.
        sa.Column(
            "location_sharing_allowed", sa.Boolean(), server_default="true", nullable=False
        ),
        *_timestamps(),
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(f"role IN {FAMILY_ROLES}", name="ck_family_members_role"),
    )
    op.create_index("ix_family_members_family_id", "family_members", ["family_id"], unique=False)
    # One family per user. Enforced here rather than only in application code, because a
    # second membership row would corrupt every permission check.
    op.create_index("uq_family_members_user_id", "family_members", ["user_id"], unique=True)
    # **Exactly one head per family.** Two heads, neither able to act on the other under the
    # spouse asymmetry, is a deadlock nobody inside the family can unpick; zero heads can only
    # be repaired by an organiser.
    op.create_index(
        "uq_family_members_one_head",
        "family_members",
        ["family_id"],
        unique=True,
        postgresql_where=sa.text("role = 'head'"),
    )

    op.create_table(
        "invites",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("trip_id", sa.UUID(), nullable=False),
        # What the invite is *for*, stated rather than inferred. A nullable `family_id` alone
        # cannot carry it: `ON DELETE SET NULL` below would silently turn a join invite into a
        # family-founding one the moment its family was deleted, and accepting it would create
        # an account and send the visitor to a setup screen they were never invited to.
        #   mode='create_family'                  -> the recipient founds a family
        #   mode='join'  AND family_id IS NOT NULL -> join that family
        #   mode='join'  AND family_id IS NULL     -> the family was deleted
        sa.Column("mode", sa.String(length=16), server_default="join", nullable=False),
        sa.Column("family_id", sa.UUID(), nullable=True),
        # Only the sha256 is stored, exactly as for session cookies. The raw token is shown
        # once at creation and is not retrievable afterwards.
        sa.Column("token_hash", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.UUID(), nullable=True),
        sa.Column("used_by", sa.UUID(), nullable=True),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"], ondelete="CASCADE"),
        # A deleted family must not take its invites' rows with it silently — the accept route
        # reports `invite_family_missing`, which needs the row to still be there.
        sa.ForeignKeyConstraint(["family_id"], ["families.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["used_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_invites_token_hash"),
        sa.CheckConstraint(f"mode IN {INVITE_MODES}", name="ck_invites_mode"),
    )
    op.create_index("ix_invites_family_id", "invites", ["family_id"], unique=False)
    op.create_index("ix_invites_expires_at", "invites", ["expires_at"], unique=False)
    op.create_index("ix_invites_trip_id", "invites", ["trip_id"], unique=False)

    # --- platform ------------------------------------------------------------------------------
    # Every file behind a row here has been re-encoded server-side with all metadata dropped,
    # GPS included. That is a property of the write path, not of this table.
    op.create_table(
        "attachments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("subject_type", sa.String(length=32), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("uploader_id", sa.UUID(), nullable=True),
        # Relative to ATTACHMENTS_DIR, never absolute: the same row is read by the API
        # container and by host-side tooling, where the directory is not the same.
        sa.Column("path", sa.Text(), nullable=False),
        # The small rendition. Avatars emit two sizes (256 and 64); other subjects may emit
        # one, so this is nullable rather than a second required file.
        sa.Column("thumb_path", sa.Text(), nullable=True),
        sa.Column("mime", sa.String(length=64), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(["uploader_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_attachments_subject", "attachments", ["subject_type", "subject_id"], unique=False
    )

    # Added last, and named, because `users` and `attachments` reference each other: an
    # attachment records its uploader, and a user points at their avatar. One side has to be
    # an ALTER after both tables exist.
    op.create_foreign_key(
        "fk_users_avatar_attachment_id",
        "users",
        "attachments",
        ["avatar_attachment_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # The cycle again, in reverse: drop the ALTERed constraint before either table.
    op.drop_constraint("fk_users_avatar_attachment_id", "users", type_="foreignkey")

    op.drop_index("ix_attachments_subject", table_name="attachments")
    op.drop_table("attachments")

    op.drop_index("ix_invites_trip_id", table_name="invites")
    op.drop_index("ix_invites_expires_at", table_name="invites")
    op.drop_index("ix_invites_family_id", table_name="invites")
    op.drop_table("invites")

    op.drop_index("uq_family_members_one_head", table_name="family_members")
    op.drop_index("uq_family_members_user_id", table_name="family_members")
    op.drop_index("ix_family_members_family_id", table_name="family_members")
    op.drop_table("family_members")

    op.drop_index("uq_families_trip_color", table_name="families")
    op.drop_index("uq_families_trip_name_lower", table_name="families")
    op.drop_index("ix_families_trip_id", table_name="families")
    op.drop_table("families")

    op.drop_index("ix_trip_stage_transitions_trip_created", table_name="trip_stage_transitions")
    op.drop_table("trip_stage_transitions")

    op.drop_index("ix_trip_category_settings_trip_id", table_name="trip_category_settings")
    op.drop_table("trip_category_settings")

    op.drop_index("ix_trip_organisers_trip_id", table_name="trip_organisers")
    op.drop_table("trip_organisers")

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

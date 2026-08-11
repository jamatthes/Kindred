"""invites.mode — say what an invite is for, rather than inferring it from a null.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-12

`plan/architecture.md` described `invites.family_id` as "nullable = invite creates a new
family", and separately required that a deleted family leave its invites "reportable as
`invite_family_missing` rather than vanishing with it" — which is why the foreign key is
`ON DELETE SET NULL`.

Those two statements cannot both hold. `ON DELETE SET NULL` is precisely the operation that
turns a join invite into something indistinguishable from a new-family invite, so an accept
after the family was deleted would silently succeed as a `create_family` acceptance and send
the visitor to a family setup screen they were never invited to. Caught by
`tests/test_invites.py::test_accepting_into_a_deleted_family_is_a_distinct_failure`, which
asserted the `409` the design promises and got a `201`.

`mode` states the purpose the two routes actually branch on. `family_id is null` then means
one thing only — the family is gone — and the two conditions are separable:

    mode = 'create_family'                     -> FM-6, the recipient founds a family
    mode = 'join' AND family_id IS NOT NULL     -> FM-5, join that family
    mode = 'join' AND family_id IS NULL         -> the family was deleted; invite_family_missing

Backfill: existing rows are `create_family` exactly when `family_id` is null, which is the
old rule. No deployed instance has had a family deleted out from under an invite (`families`
has not shipped), so the backfill is exact rather than a best guess.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INVITE_MODES = ("join", "create_family")


def upgrade() -> None:
    op.add_column(
        "invites",
        sa.Column("mode", sa.String(length=16), server_default="join", nullable=False),
    )
    op.execute("UPDATE invites SET mode = 'create_family' WHERE family_id IS NULL")
    op.create_check_constraint(
        "ck_invites_mode", "invites", "mode IN " + str(INVITE_MODES)
    )


def downgrade() -> None:
    op.drop_constraint("ck_invites_mode", "invites", type_="check")
    op.drop_column("invites", "mode")

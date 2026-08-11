"""Typed access to the ``settings`` key/value table.

One path in and one path out, so the scalar keys (`instance_name`, `invite_only`) and the
one structured key (`google_api_status`, a JSON object) are read and written the same way.
Before this existed there were two: `routers/settings.py` selecting rows directly for the
public read, and whatever each writer invented. A second implementation of "read a setting"
is a second place for a default to differ.

The column is ``JSONB``, so a value is already whatever JSON shape it was stored as; nothing
here serialises or parses. What this module adds is the *absence* case — a key that has never
been written — and the guarantee that writing is an upsert rather than an insert that fails
the second time.

Named ``settings_store`` and not ``settings`` deliberately: ``app.core.config.settings`` is
the environment, and two things called "settings" one import apart would be a trap.
"""

from __future__ import annotations

from typing import Any, TypeVar

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Setting

T = TypeVar("T")


async def get_setting(db: AsyncSession, key: str, default: T) -> Any | T:
    """The stored value, or ``default`` when the key has never been written.

    A missing key is not an error: a fresh install has never run the Google probe, and the
    honest answer to "what was the last result?" is the caller's default, not an exception.
    """
    row = await db.scalar(select(Setting).where(Setting.key == key))
    return default if row is None else row.value


async def set_setting(db: AsyncSession, key: str, value: Any) -> None:
    """Upsert. Does **not** commit — the caller owns the transaction boundary.

    ``ON CONFLICT DO UPDATE`` rather than read-then-write: two admins pressing `Run check` at
    the same moment should leave one of the two results, not raise a unique-violation at
    whichever lost.
    """
    await db.execute(
        pg_insert(Setting)
        .values(key=key, value=value)
        .on_conflict_do_update(index_elements=[Setting.key], set_={"value": value})
    )

"""The migration and the models must describe the same schema. This proves it.

`CLAUDE.md` states the rule: "every constraint and index in the migration is mirrored in
`__table_args__`, because the test suite builds its schema with `create_all` and a constraint
living in only one of the two would be enforced in exactly the place it is least tested."

Until now that rule was kept by hand and checked by hand. It is exactly the kind of rule that
holds for three features and then quietly stops, because nothing fails when it is broken —
the suite goes on passing against a schema production will not have. So it is checked here,
mechanically, on every run.

**How.** A scratch database is built by `alembic upgrade head`, and Alembic's own
`compare_metadata` then diffs the models' metadata against it. That is the same machinery
`alembic revision --autogenerate` uses to decide what a migration would need to contain. Here
it should decide: nothing. Anything else is printed as the list of operations Alembic would
generate to reconcile the two, which is a readable description of the drift.

No new driver: the scratch database is created with `asyncpg` and reflected through the async
engine, with `run_sync` handing Alembic the synchronous connection it needs.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncpg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import settings
from app.models import Base

SERVER_DIR = Path(__file__).resolve().parents[1]

#: A throwaway database owned by this test alone. Named distinctly so a developer who sees it
#: in psql knows what it is and that nothing depends on it.
SCRATCH_DB = "kindred_schemacheck"


def _async_url(database: str) -> str:
    parts = urlsplit(settings.database_url)
    return urlunsplit(parts._replace(path=f"/{database}"))


def _admin_dsn() -> str:
    parts = urlsplit(settings.database_url)
    return urlunsplit(
        parts._replace(scheme="postgresql", path="/postgres", query="", fragment="")
    )


async def _recreate(database: str) -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{database}"')
        await conn.execute(f'CREATE DATABASE "{database}"')
    finally:
        await conn.close()


async def _drop(database: str) -> None:
    conn = await asyncpg.connect(_admin_dsn())
    try:
        await conn.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            database,
        )
        await conn.execute(f'DROP DATABASE IF EXISTS "{database}"')
    finally:
        await conn.close()


def _include_object(obj, name, type_, reflected, compare_to) -> bool:
    """Alembic's own bookkeeping table is not part of the schema under test."""
    return name != "alembic_version"


async def _differences() -> list:
    engine = create_async_engine(_async_url(SCRATCH_DB))
    try:
        async with engine.connect() as conn:

            def _compare(sync_conn):
                context = MigrationContext.configure(
                    sync_conn,
                    opts={
                        # Types and server defaults round-trip imperfectly through
                        # reflection (VARCHAR length vs String, `'false'` vs `false`), and
                        # flagging those would make the test noise rather than signal. What
                        # is compared is the part that matters and that drifts: tables,
                        # columns, nullability, indexes and constraints.
                        "compare_type": False,
                        "compare_server_default": False,
                        "include_object": _include_object,
                    },
                )
                return compare_metadata(context, Base.metadata)

            return await conn.run_sync(_compare)
    finally:
        await engine.dispose()


def test_the_migration_and_the_models_agree() -> None:
    """`alembic upgrade head` must produce exactly what the models describe.

    Synchronous, and running its own event loop: Alembic's command API is sync, and this test
    owns its own database rather than sharing the suite's engine.
    """

    async def _build() -> list:
        await _recreate(SCRATCH_DB)
        return []

    asyncio.run(_build())
    try:
        config = Config(str(SERVER_DIR / "alembic.ini"))
        config.set_main_option("script_location", str(SERVER_DIR / "alembic"))
        # `alembic/env.py` deliberately takes the URL from `settings`, never from the ini, so
        # pointing this run at the scratch database means pointing `settings` at it. Restored
        # in the `finally` below — the rest of the suite shares that singleton.
        original = settings.database_url
        settings.database_url = _async_url(SCRATCH_DB)
        try:
            command.upgrade(config, "head")
            differences = asyncio.run(_differences())
        finally:
            settings.database_url = original

        assert not differences, (
            "The migration and the models have drifted apart. Alembic would generate the "
            "following to reconcile them:\n  "
            + "\n  ".join(repr(diff) for diff in differences)
        )
    finally:
        asyncio.run(_drop(SCRATCH_DB))


@pytest.mark.parametrize(
    "table",
    ["polls", "poll_options", "poll_scores", "comments", "notifications"],
)
def test_the_polls_tables_are_in_the_models(table: str) -> None:
    """A cheap guard on the expensive test above: if a table is missing from the metadata
    entirely, say so plainly rather than through an Alembic diff."""
    assert table in Base.metadata.tables

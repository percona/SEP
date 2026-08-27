# Copyright (C) 2026 Percona LLC
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.

"""Build test-database schemas from a DDL script captured once per worker.

``metadata.create_all`` is the obvious way to give a test its tables, but almost
none of its per-call cost is the DDL: it recompiles every statement, sorts the
tables, and — with the default ``checkfirst=True`` — reflects one ``has_table``
probe per table. Capturing that DDL once and replaying it through a single
``executescript`` round-trip leaves each test the same brand-new empty database
for a fraction of the setup.

The cache is per-process, so each xdist worker captures once and every test in
that worker replays. It is keyed on the metadata object itself (which keeps the
object alive, so identity can never be recycled), the connection's
``schema_translate_map``, and a fingerprint of every table's DDL-bearing parts —
a metadata mutated after first capture misses the cache instead of being served
a stale schema.
"""

from collections.abc import Iterable
from typing import Any

from sqlalchemy import create_engine, event, MetaData
from sqlalchemy.ext.asyncio import AsyncConnection

_TableShape = tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]]
_ScriptKey = tuple[
    MetaData, tuple[tuple[str, str | None], ...], tuple[_TableShape, ...]
]

_SCRIPTS: dict[_ScriptKey, str] = {}


def capture_ddl(metadata: MetaData, translate_map: dict[str, str | None] | None) -> str:
    """Return the DDL ``create_all`` would emit, as one executable script.

    Runs against a real *synchronous* in-memory engine rather than
    ``create_mock_engine`` so that ``schema_translate_map`` — which is applied at
    execution time, not at compile time — reaches the emitted statements. Under a
    mock engine every celery-beat statement comes back carrying a
    ``celery_schema.`` prefix that no SQLite database has.

    Only ``CREATE`` statements are kept. That drops nothing today — both
    metadatas emit ``CREATE``-only DDL — and the equivalence test compares the
    resulting ``sqlite_master`` against ``create_all``'s, so anything the filter
    did drop would surface there rather than silently.

    :param metadata: The metadata whose tables and indexes are emitted.
    :param translate_map: The schema translate map to apply while emitting, or
        ``None`` for metadata that declares no schema.
    :return: The captured ``CREATE`` statements joined into one script.
    """
    statements: list[str] = []
    engine = create_engine(
        "sqlite://",
        execution_options=(
            {"schema_translate_map": translate_map} if translate_map else {}
        ),
    )

    @event.listens_for(engine, "before_cursor_execute")
    def _record(_conn: Any, _cursor: Any, statement: str, *_args: Any) -> None:
        """Append each statement the engine is about to execute."""
        statements.append(statement.strip())

    try:
        with engine.begin() as conn:
            metadata.create_all(conn, checkfirst=False)
    finally:
        engine.dispose()
    return _join(s for s in statements if s.upper().startswith("CREATE"))


def _join(statements: Iterable[str]) -> str:
    """Return ``statements`` as one ``executescript``-ready SQL script.

    :param statements: The captured DDL statements, without terminators.
    :return: The statements terminated and separated by semicolons.
    """
    return "".join(f"{statement};\n" for statement in statements)


def _shape(metadata: MetaData) -> tuple[_TableShape, ...]:
    """Return the DDL-bearing shape of every table in ``metadata``.

    The cache key's invalidation term. A table count alone tracks only whole
    tables, so a column, index or constraint appended to an existing one would
    change the emitted DDL while still hitting the entry captured before it.

    :param metadata: The metadata to fingerprint.
    :return: One ``(table, columns, indexes, constraints)`` entry per table, in
        name order, each inner tuple carrying names only.
    """
    return tuple(
        (
            name,
            tuple(column.name for column in table.columns),
            tuple(sorted(index.name or "" for index in table.indexes)),
            tuple(sorted(str(c.name) if c.name else "" for c in table.constraints)),
        )
        for name, table in sorted(metadata.tables.items())
    )


async def apply_schema(conn: AsyncConnection, metadata: MetaData) -> None:
    """Create every table in ``metadata`` on ``conn``, from a cached DDL script.

    Drop-in replacement for ``await conn.run_sync(metadata.create_all)`` **on an
    async in-memory SQLite connection only** — ``executescript`` is an
    aiosqlite-specific API with no asyncpg equivalent, so a real-PostgreSQL or
    real-MySQL call site must keep calling ``create_all``. The
    ``schema_translate_map`` is read off the connection, so a call site that sets
    one on its engine needs no extra argument.

    ``executescript`` issues an implicit ``COMMIT`` before it runs, so it ends
    any transaction already open on ``conn`` — writes issued after it in the same
    ``engine.begin()`` block still commit normally.

    :param conn: The async SQLite connection the schema is created on.
    :param metadata: The metadata whose tables and indexes are created.
    """
    translate_map = conn.sync_connection.get_execution_options().get(
        "schema_translate_map"
    )
    key = (
        metadata,
        tuple(sorted((translate_map or {}).items(), key=lambda kv: str(kv[0]))),
        _shape(metadata),
    )
    script = _SCRIPTS.get(key)
    if script is None:
        script = capture_ddl(metadata, translate_map)
        _SCRIPTS[key] = script
    raw = await conn.get_raw_connection()
    await raw.driver_connection.executescript(script)

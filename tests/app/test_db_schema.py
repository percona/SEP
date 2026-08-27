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

"""Pin the premises :func:`tests.app.db_schema.apply_schema` trades against.

``apply_schema`` replaces ``metadata.create_all`` in every async-SQLite test
fixture, so three things have to stay true or the substitution is unsound: the
schema it materialises is the one ``create_all`` would have built, the
``schema_translate_map`` reaches the emitted DDL, and each new engine still
starts empty. The isolation guards are written so that reusing one engine — the
shortcut the whole approach exists to avoid — turns them red.
"""

import pytest
from sqlalchemy import Column, func, Integer, MetaData, select, Table, text
from sqlalchemy.ext.asyncio import (
    AsyncConnection,
    AsyncEngine,
    AsyncSession,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool
from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel import SQLModel

from app.sep.models import AppLifecycleEnum, AppState
from tests.app.db_schema import apply_schema, capture_ddl

pytest_plugins = ["pytester"]

_CELERY_METADATA = PeriodicTask.__table__.metadata
_CELERY_TRANSLATE_MAP = {"celery_schema": None}
_PROBE_APP_KEY = "db-schema-isolation-probe"

_SCHEMA_QUERY = text(
    "SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"
)

_CHILD_SUITE = """
import pytest
from sqlalchemy import func, select

from app.sep.models import AppState


@pytest.mark.asyncio
async def test_a_commits_a_row(session):
    session.add(AppState(app_key="fixture-isolation-probe"))
    await session.commit()


@pytest.mark.asyncio
async def test_b_sees_an_empty_table(session):
    count = await session.scalar(select(func.count()).select_from(AppState))
    assert count == 0
"""


def _engine(*, translate_map: dict[str, str | None] | None = None) -> AsyncEngine:
    """Return an in-memory async SQLite engine shaped like the suite's fixtures.

    :param translate_map: The ``schema_translate_map`` to bind, for metadata that
        declares a schema.
    :return: A fresh ``AsyncEngine`` over its own private database.
    """
    engine = create_async_engine("sqlite+aiosqlite://", poolclass=StaticPool)
    if translate_map is not None:
        engine = engine.execution_options(schema_translate_map=translate_map)
    return engine


async def _schema_rows(conn: AsyncConnection) -> list[tuple[str, ...]]:
    """Return every ``sqlite_master`` row on ``conn`` as a comparable tuple.

    :param conn: The connection whose catalogue is read.
    :return: ``(type, name, tbl_name, sql)`` for each object, ordered.
    """
    result = await conn.execute(_SCHEMA_QUERY)
    return [tuple(row) for row in result]


async def _rows_after_create_all(
    metadata: MetaData, *, translate_map: dict[str, str | None] | None = None
) -> list[tuple[str, ...]]:
    """Return the catalogue ``metadata.create_all`` produces on a fresh database.

    :param metadata: The metadata to create.
    :param translate_map: The ``schema_translate_map`` to bind on the engine.
    :return: The resulting ``sqlite_master`` rows.
    """
    engine = _engine(translate_map=translate_map)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
            return await _schema_rows(conn)
    finally:
        await engine.dispose()


async def _rows_after_apply_schema(
    metadata: MetaData, *, translate_map: dict[str, str | None] | None = None
) -> list[tuple[str, ...]]:
    """Return the catalogue :func:`apply_schema` produces on a fresh database.

    :param metadata: The metadata to create.
    :param translate_map: The ``schema_translate_map`` to bind on the engine.
    :return: The resulting ``sqlite_master`` rows.
    """
    engine = _engine(translate_map=translate_map)
    try:
        async with engine.begin() as conn:
            await apply_schema(conn, metadata)
            return await _schema_rows(conn)
    finally:
        await engine.dispose()


class TestSchemaEquivalence:
    """Prove the captured DDL builds the same schema ``create_all`` would."""

    @pytest.mark.asyncio
    async def test_matches_create_all_for_sqlmodel_metadata(self) -> None:
        """Assert the app metadata materialises identically through both paths."""
        expected = await _rows_after_create_all(SQLModel.metadata)

        actual = await _rows_after_apply_schema(SQLModel.metadata)

        assert actual == expected

    @pytest.mark.asyncio
    async def test_matches_create_all_for_celery_beat_metadata(self) -> None:
        """Assert the translate-mapped celery-beat metadata matches too.

        The celery-beat tables declare a ``celery_schema`` that the fixtures map
        away; this is the case a compile-time-only capture gets wrong.
        """
        expected = await _rows_after_create_all(
            _CELERY_METADATA, translate_map=_CELERY_TRANSLATE_MAP
        )

        actual = await _rows_after_apply_schema(
            _CELERY_METADATA, translate_map=_CELERY_TRANSLATE_MAP
        )

        assert actual == expected

    def test_celery_beat_capture_resolves_the_schema_prefix(self) -> None:
        """Assert no captured celery-beat statement keeps a ``celery_schema.`` prefix.

        ``schema_translate_map`` is applied at execution time, so a capture taken
        through ``create_mock_engine`` — which never executes — would leave every
        statement naming a schema no SQLite database has.
        """
        script = capture_ddl(_CELERY_METADATA, _CELERY_TRANSLATE_MAP)

        assert "CREATE TABLE" in script
        assert "celery_schema." not in script


class TestDataIsolation:
    """Prove each engine still gets a private, empty database."""

    @pytest.mark.asyncio
    async def test_a_committed_row_does_not_reach_the_next_engine(self) -> None:
        """Assert a committed row dies with the engine that wrote it.

        Two engine lifetimes inside one test, so the assertion holds regardless
        of test order, worker assignment, or fixture scope. Reusing a single
        engine across both halves — the shortcut this design rejects — is what
        turns it red.
        """
        writer = _engine()
        try:
            async with writer.begin() as conn:
                await apply_schema(conn, SQLModel.metadata)
            async with AsyncSession(writer) as session:
                session.add(AppState(app_key=_PROBE_APP_KEY))
                await session.commit()
        finally:
            await writer.dispose()

        reader = _engine()
        try:
            async with reader.begin() as conn:
                await apply_schema(conn, SQLModel.metadata)
            async with AsyncSession(reader) as session:
                count = await session.scalar(select(func.count()).select_from(AppState))
        finally:
            await reader.dispose()

        assert count == 0

    @pytest.mark.asyncio
    async def test_a_write_after_apply_schema_still_commits(self) -> None:
        """Assert the implicit COMMIT inside ``executescript`` costs no later write.

        ``executescript`` commits before it runs, ending the transaction
        ``engine.begin()`` opened. The write issued after it must still be
        durable, which is what every converted fixture relies on.
        """
        engine = _engine()
        try:
            async with engine.begin() as conn:
                await apply_schema(conn, SQLModel.metadata)
                await conn.execute(
                    AppState.__table__.insert().values(
                        app_key=_PROBE_APP_KEY,
                        lifecycle_state=AppLifecycleEnum.ENABLED,
                    )
                )
            async with AsyncSession(engine) as session:
                stored = await session.scalar(select(AppState.app_key))
        finally:
            await engine.dispose()

        assert stored == _PROBE_APP_KEY

    def test_the_shared_session_fixture_starts_each_test_empty(
        self, pytester: pytest.Pytester
    ) -> None:
        """Assert the real ``session`` fixture hands the next test an empty table.

        Binds the actual fixture rather than the helper, in a fixed order under a
        single process so the second test provably runs after the first committed.
        """
        pytester.makeconftest('pytest_plugins = ["tests.app.conftest"]')
        pytester.makepyfile(test_fixture_isolation=_CHILD_SUITE)

        result = pytester.runpytest("-p", "no:cacheprovider", "-n0")

        result.assert_outcomes(passed=2)


class TestScriptCache:
    """Pin the cache key against serving a stale script."""

    @pytest.mark.asyncio
    async def test_metadata_that_gains_a_table_is_recaptured(self) -> None:
        """Assert a table added after the first capture still gets created.

        The table count is part of the cache key precisely so a metadata object
        mutated between calls misses instead of replaying the older schema.
        """
        metadata = MetaData()
        Table("first_probe", metadata, Column("id", Integer, primary_key=True))
        await _rows_after_apply_schema(metadata)
        Table("second_probe", metadata, Column("id", Integer, primary_key=True))

        rows = await _rows_after_apply_schema(metadata)

        assert {name for _type, name, *_rest in rows} >= {
            "first_probe",
            "second_probe",
        }

    @pytest.mark.asyncio
    async def test_equal_sized_metadata_objects_do_not_share_an_entry(self) -> None:
        """Keep two same-sized metadata objects on separate cache entries.

        The metadata object itself is the first element of the cache key, so two
        unrelated schemas that happen to declare the same number of tables must
        never be served each other's DDL.
        """
        first = MetaData()
        Table("alpha_probe", first, Column("id", Integer, primary_key=True))
        second = MetaData()
        Table("beta_probe", second, Column("id", Integer, primary_key=True))
        await _rows_after_apply_schema(first)

        rows = await _rows_after_apply_schema(second)

        names = {name for _type, name, *_rest in rows}
        assert "beta_probe" in names
        assert "alpha_probe" not in names

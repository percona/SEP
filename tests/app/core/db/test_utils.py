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

"""Define tests for the app.core.db.utils module."""

from contextlib import nullcontext
from unittest.mock import MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import Column, Integer, JSON, MetaData, select, Table, Text
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql import column
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.config import DatabaseOptions
from app.core.db.utils import (
    compare_type,
    create_app_async_engine,
    func_json_extract,
    get_async_session_maker_from_engine,
    idempotent_insert,
    NullsLastOrdering,
)
from app.core.utils.fields import AsyncDatabaseEngine, DatabaseDialect
from app.tasks.crud import TaskHistoryManager, TaskManager
from app.tasks.models import TaskExecutionRequestJSON, TaskHistory, TaskWrite
from tests.app.factories import build_task_history, TaskFactory


@pytest.mark.asyncio
async def test_get_async_session_maker_from_engine():
    """Verify that the sessionmaker is correctly configured with AsyncSession and expire_on_commit=False."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        session_maker = get_async_session_maker_from_engine(engine)
        assert session_maker.kw.get("expire_on_commit") is False

        async with session_maker() as session:
            assert isinstance(session, AsyncSession)
    finally:
        await engine.dispose()


@pytest.fixture
def sample_table():
    """Return a minimal SQLAlchemy Table for dispatch tests."""
    metadata = MetaData()
    return Table("sample", metadata, Column("id", Integer, primary_key=True))


class TestIdempotentInsert:
    """Test the dialect-aware ``idempotent_insert`` helper."""

    @pytest.mark.parametrize(
        (
            "dialect_name",
            "dialect",
            "expected_cls",
            "expected_substring",
            "expectation",
        ),
        [
            (
                "postgresql",
                postgresql.dialect(),
                postgresql.Insert,
                "ON CONFLICT DO NOTHING",
                nullcontext(),
            ),
            (
                "sqlite",
                sqlite.dialect(),
                sqlite.Insert,
                "ON CONFLICT DO NOTHING",
                nullcontext(),
            ),
            (
                "oracle",
                None,
                None,
                None,
                pytest.raises(NotImplementedError, match="oracle"),
            ),
        ],
        ids=["postgresql", "sqlite", "unknown_dialect_raises"],
    )
    def test_idempotent_insert_dispatch(
        self,
        sample_table,
        dialect_name,
        dialect,
        expected_cls,
        expected_substring,
        expectation,
    ):
        """Assert dialect dispatch produces the right idempotent insert, or raises for unknown dialects.

        PostgreSQL and SQLite emit ``ON CONFLICT DO NOTHING``; an unsupported
        dialect raises ``NotImplementedError``.
        """
        with expectation:
            stmt = idempotent_insert(dialect_name, sample_table)
            assert isinstance(stmt, expected_cls)
            compiled = str(stmt.compile(dialect=dialect))
            assert expected_substring in compiled.upper()


def _compile(expr, dialect) -> str:
    return str(expr.compile(dialect=dialect, compile_kwargs={"literal_binds": True}))


def _compile_postcompile(expr, dialect) -> str:
    return str(
        expr.compile(dialect=dialect, compile_kwargs={"render_postcompile": True})
    )


def _assert_ordered(rendered: str, fragments: list[str]) -> None:
    """Assert each fragment appears in ``rendered`` in the given left-to-right order.

    :param rendered: the compiled SQL string under inspection.
    :param fragments: substrings expected to appear in this exact order, each
        strictly after the previous one.
    """
    pos = -1
    for fragment in fragments:
        index = rendered.find(fragment, pos + 1)
        assert index != -1, (
            f"{fragment!r} not found after position {pos} in {rendered!r}"
        )
        pos = index


@pytest.fixture
def ordering_table():
    """Return a table with a nullable sort column, a JSON column, and a tie-breaker."""
    metadata = MetaData()
    return Table(
        "item",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("parent_id", Integer),
        Column("meta", JSON),
    )


class TestNullsLastOrdering:
    """Cover the ``NullsLastOrdering`` construct and its compiler hook."""

    @pytest.mark.parametrize(
        "dialect",
        [postgresql.dialect(), sqlite.dialect()],
        ids=["postgresql", "sqlite"],
    )
    @pytest.mark.parametrize("descending", [False, True], ids=["asc", "desc"])
    def test_renders_nulls_last_on_postgresql_and_sqlite(
        self, ordering_table, dialect, descending
    ):
        """Reproduce the ``.nulls_last()`` baseline rendering on both dialects."""
        sort_column = ordering_table.c.parent_id
        baseline = sort_column.desc() if descending else sort_column.asc()

        rendered = _compile(
            NullsLastOrdering(sort_column, descending=descending), dialect
        )

        assert rendered == _compile(baseline.nulls_last(), dialect)

    def test_tie_breaker_remains_final_order_by_term(self, ordering_table):
        """Keep the tie-breaker as the final ``ORDER BY`` term."""
        query = select(ordering_table.c.id).order_by(
            NullsLastOrdering(ordering_table.c.parent_id, descending=True),
            ordering_table.c.id.asc(),
        )

        rendered = _compile(query, postgresql.dialect())

        assert rendered.endswith("ORDER BY item.parent_id DESC NULLS LAST, item.id ASC")

    def test_nulls_last_ordering_is_cacheable(self, ordering_table):
        """Produce a real cache key that discriminates both column and direction."""

        def cache_key(sort_column, *, descending):
            return (
                select(ordering_table.c.id)
                .order_by(NullsLastOrdering(sort_column, descending=descending))
                ._generate_cache_key()
            )

        ascending = cache_key(ordering_table.c.parent_id, descending=False)

        assert ascending is not None
        assert ascending == cache_key(ordering_table.c.parent_id, descending=False)
        assert ascending != cache_key(ordering_table.c.parent_id, descending=True)
        assert ascending != cache_key(ordering_table.c.id, descending=False)

    def test_wrapped_expression_inlines_only_its_code_constant_path(
        self, ordering_table
    ):
        """Render the ``literal_execute`` JSON path inline in the single ordering term.

        ``func_json_extract`` builds its path with ``literal_execute``, so the
        dialect's literal processor -- not a bound parameter -- emits it at
        execution. The value is a code constant inlined into the one
        ``NULLS LAST`` term the standard hook renders.
        """
        extract = func_json_extract(
            DatabaseDialect.POSTGRESQL, ordering_table.c.meta, "title"
        )
        query = select(ordering_table.c.id).order_by(NullsLastOrdering(extract))

        executed = query.compile(
            dialect=postgresql.dialect(), compile_kwargs={"render_postcompile": True}
        )

        assert str(executed).endswith("ORDER BY item.meta ->> 'title' ASC NULLS LAST")
        assert executed.params == {}

    def test_raw_string_column_becomes_a_bound_parameter(self, ordering_table):
        """Bind a raw string argument instead of splicing it into the ORDER BY."""
        injected = "parent_id; DROP TABLE item --"

        compiled = (
            select(ordering_table.c.id)
            .order_by(NullsLastOrdering(injected))
            .compile(dialect=postgresql.dialect())
        )

        assert "DROP TABLE" not in str(compiled)
        assert injected in compiled.params.values()


@pytest.mark.parametrize(
    ("path", "ordered"),
    [
        (("task",), ["->>", "'task'"]),
        (("meta", "key"), ["->", "'meta'", "->>", "'key'"]),
    ],
    ids=["single_key", "nested_path"],
)
def test_func_json_extract_postgresql_json_column_arrow_chain(path, ordered):
    """Render the PostgreSQL ``->`` / ``->>`` arrow chain for single and nested paths.

    A single-element path renders ``col ->> 'key'``; a nested path chains
    ``->`` for the intermediate key then ``->>`` for the leaf. A native
    ``JSON`` column uses neither ``json_extract_path_text`` nor a ``CAST``
    wrapper.
    """
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("postgresql", json_column, *path)

    rendered = _compile(expression, postgresql.dialect())
    _assert_ordered(rendered, ordered)
    assert "json_extract_path_text" not in rendered
    assert "CAST" not in rendered.upper()


@pytest.mark.parametrize(
    ("path", "ordered_upper"),
    [
        (("task_name",), ["CAST", "AS JSON", "->>", "'TASK_NAME'"]),
        (("meta", "key"), ["CAST", "AS JSON", "->", "'META'", "->>", "'KEY'"]),
    ],
    ids=["single_key", "nested_path"],
)
def test_func_json_extract_postgresql_text_column_wraps_in_cast(path, ordered_upper):
    """Wrap ``text``-typed columns in ``CAST(... AS JSON)`` before the arrow chain.

    PostgreSQL does not define the ``->>`` operator on ``text``, so text
    columns must be cast to ``json`` first — without it queries raise
    ``operator does not exist: text ->> unknown`` at execution time, the exact
    failure mode this ticket fixes for ``celery_periodictask.kwargs``. The cast
    sits on the root column once; for a nested path ``(a, b)`` the shape is
    ``(CAST(col AS JSON) -> 'a') ->> 'b'`` so every operator sees a JSON LHS.
    """
    text_column = column("kwargs", type_=Text())

    expression = func_json_extract("postgresql", text_column, *path)

    rendered = _compile(expression, postgresql.dialect()).upper()
    _assert_ordered(rendered, ordered_upper)


def test_func_json_extract_postgresql_jsonb_column_does_not_wrap_in_cast():
    """Keep ``jsonb`` columns unwrapped so the functional expression indexes match.

    ``taskhistory.execution_request`` is ``jsonb`` and carries
    functional expression indexes on ``(execution_request ->> 'task')`` etc.
    Adding a ``CAST`` wrapper would change the expression shape and stop the
    planner from matching those indexes — this test pins that contract.
    """
    jsonb_column = column("execution_request", type_=JSONB())

    expression = func_json_extract("postgresql", jsonb_column, "task")

    rendered = _compile(expression, postgresql.dialect())
    assert "->>" in rendered
    assert "'task'" in rendered
    assert "CAST" not in rendered.upper()


def test_func_json_extract_postgresql_auto_json_column_does_not_wrap_in_cast():
    """Unwrap ``TypeDecorator`` chains (``AutoJSON``) before the JSON check.

    ``TaskHistory.execution_request`` is declared as ``TaskExecutionRequestJSON``,
    a subclass of ``AutoJSON`` which is itself a ``TypeDecorator`` whose impl
    is ``JSON``. A naive ``isinstance(col.type, JSON)`` check would return
    ``False`` and add an unwanted ``CAST``. Pin that unwrapping recognises
    the underlying JSON impl and emits the index-compatible shape.
    """
    mapped_column = col(TaskHistory.execution_request)

    expression = func_json_extract("postgresql", mapped_column, "task")

    rendered = _compile(expression, postgresql.dialect())
    assert "->>" in rendered
    assert "CAST" not in rendered.upper()


def test_func_json_extract_single_key_renders_json_extract():
    """Render ``json_extract(col, '$.task')`` on SQLite for a single-element path."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("sqlite", json_column, "task")

    rendered = _compile(expression, sqlite.dialect())
    assert "json_extract" in rendered.lower()
    assert "'$.task'" in rendered


def test_func_json_extract_sqlite_nested_path_renders_dotted_path():
    """Render ``json_extract(col, '$.meta.key')`` on SQLite for a nested path."""
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("sqlite", json_column, "meta", "key")

    rendered = _compile(expression, sqlite.dialect())
    assert "json_extract" in rendered.lower()
    assert "'$.meta.key'" in rendered


def test_func_json_extract_postgresql_mapped_column_binds_path_as_text():
    """Force text-typed binds for PG JSON operators on mapped ORM columns.

    SQLAlchemy infers bind parameter types from the LHS column type. Using a
    mapped JSON attribute directly would otherwise render
    ``col ->> %(param)s::JSON``, which is invalid SQL because PostgreSQL's
    ``->`` / ``->>`` operators only accept ``text`` / ``integer`` RHS operands.
    """
    mapped_column = col(TaskHistory.execution_request)

    single = func_json_extract("postgresql", mapped_column, "task")
    nested = func_json_extract("postgresql", mapped_column, "meta", "key")

    single_sql = str(single.compile(dialect=postgresql.dialect()))
    nested_sql = str(nested.compile(dialect=postgresql.dialect()))
    assert "::JSON" not in single_sql.upper()
    assert "::JSON" not in nested_sql.upper()


def test_func_json_extract_postgresql_equality_compiles_with_literal_binds():
    """Render equality comparisons with literal binds on PostgreSQL.

    The helper must return a text-typed expression so callers comparing the
    result against a string (e.g. ``extract(...) == queue_item.task``) can
    bind the RHS value as text. A JSON-typed return would try to render the
    RHS as a JSON literal and raise a ``CompileError``.
    """
    mapped_column = col(TaskHistory.execution_request)

    single = func_json_extract("postgresql", mapped_column, "task") == "mysqldump"
    nested = (
        func_json_extract("postgresql", mapped_column, "meta", "origin") == "scheduler"
    )

    single_sql = str(
        single.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    nested_sql = str(
        nested.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )
    assert "'mysqldump'" in single_sql
    assert "'scheduler'" in nested_sql


def test_func_json_extract_postgresql_path_is_inlined_for_index_match():
    """Inline JSON path constants so PG expression indexes can be matched.

    PostgreSQL expression indexes like
    ``CREATE INDEX ... ON taskhistory ((execution_request->>'task'))`` only
    match queries whose arrow expression contains the same literal key, not
    a bound parameter. Render the helper with post-compile expansion to
    confirm the path element appears as an inline literal (``'task'``)
    rather than a parameter placeholder.
    """
    mapped_column = col(TaskHistory.execution_request)

    expression = func_json_extract("postgresql", mapped_column, "task")

    rendered = _compile_postcompile(expression, postgresql.dialect())
    assert "->> 'task'" in rendered or "->>'task'" in rendered


def test_func_json_extract_sqlite_path_is_inlined_for_index_match():
    """Inline JSON path constants so SQLite expression indexes can be matched.

    SQLite's ``CREATE INDEX ... ON taskhistory (json_extract(execution_request, '$.task'))``
    is only used when the query renders the same literal path. Confirm the
    helper emits ``json_extract(..., '$.task')`` rather than a parameter
    placeholder for the path argument.
    """
    json_column = column("execution_request", type_=JSON)

    expression = func_json_extract("sqlite", json_column, "task")

    rendered = _compile_postcompile(expression, sqlite.dialect())
    assert "'$.task'" in rendered
    assert "?" not in rendered


def test_compare_type_suppresses_diff_for_task_execution_request_json_against_json():
    """Suppress spurious Alembic diffs when ``TaskExecutionRequestJSON`` meets ``JSON``.

    ``compare_type`` must recognise ``TaskExecutionRequestJSON`` as a subclass
    of ``AutoJSON`` and return ``False`` so Alembic autogeneration does not
    propose a no-op type change against an inspected ``JSON`` column.
    """
    result = compare_type(
        context=MagicMock(),
        inspected_column=MagicMock(),
        metadata_column=MagicMock(),
        inspected_type=JSON(),
        metadata_type=TaskExecutionRequestJSON(),
    )
    assert result is False


def test_compare_type_suppresses_diff_for_task_execution_request_json_against_jsonb():
    """Suppress spurious Alembic diffs when ``TaskExecutionRequestJSON`` meets ``JSONB``.

    Pin the contract that flipping ``TaskExecutionRequestJSON`` to inherit
    from ``AutoJSON`` keeps autogeneration quiet against the ``jsonb`` column
    that PostgreSQL exposes after the migration runs.
    """
    result = compare_type(
        context=MagicMock(),
        inspected_column=MagicMock(),
        metadata_column=MagicMock(),
        inspected_type=JSONB(),
        metadata_type=TaskExecutionRequestJSON(),
    )
    assert result is False


_PROBE_METADATA = MetaData()
_json_probe = Table(
    "json_extract_probe",
    _PROBE_METADATA,
    Column("id", Integer, primary_key=True),
    Column("payload_json", JSON),
    Column("payload_jsonb", JSONB),
    Column("payload_text", Text),
)


@pytest_asyncio.fixture
async def json_probe_session(postgres_engine: AsyncEngine) -> AsyncSession:
    """Create the module-local JSON probe table on real PG and yield a session.

    Layered on the shared ``postgres_engine`` so cells 1-3 exercise
    ``func_json_extract`` against ``json``/``jsonb``/``text`` columns without
    depending on the tasks-service schema.
    """
    async with postgres_engine.begin() as conn:
        await conn.run_sync(_PROBE_METADATA.create_all)
    async_session_maker = get_async_session_maker_from_engine(postgres_engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        async with postgres_engine.begin() as conn:
            await conn.run_sync(_PROBE_METADATA.drop_all)


class TestFuncJsonExtractOnRealPostgres:
    """Execute ``func_json_extract`` end-to-end against a real PostgreSQL engine.

    Siblings to the compile-only render tests above: those pin the emitted SQL
    *shape*, these prove the SQL the helper emits actually executes on PostgreSQL
    and returns the expected scalar. SQLite cannot substitute — its
    ``json_extract`` accepts ``text``, so the ``text``-to-``CAST`` branch (the
    text-column regression surface) is untestable there.
    """

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_json_column_extracts_single_key_scalar(
        self, json_probe_session: AsyncSession
    ):
        """Execute a single-element arrow path against a real ``json`` column."""
        name = json_probe_session.get_bind().name
        await json_probe_session.exec(
            _json_probe.insert().values(id=1, payload_json={"task": "mysqldump"})
        )
        await json_probe_session.commit()

        result = await json_probe_session.exec(
            select(func_json_extract(name, _json_probe.c.payload_json, "task"))
        )
        assert result.scalar_one() == "mysqldump"

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_json_column_extracts_nested_key_scalar(
        self, json_probe_session: AsyncSession
    ):
        """Execute a nested arrow chain (``-> ... ->>``) against a real ``json`` column."""
        name = json_probe_session.get_bind().name
        await json_probe_session.exec(
            _json_probe.insert().values(id=1, payload_json={"meta": {"key": "v"}})
        )
        await json_probe_session.commit()

        result = await json_probe_session.exec(
            select(func_json_extract(name, _json_probe.c.payload_json, "meta", "key"))
        )
        assert result.scalar_one() == "v"

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_jsonb_column_extracts_scalar(self, json_probe_session: AsyncSession):
        """Execute the arrow chain against a real ``jsonb`` column."""
        name = json_probe_session.get_bind().name
        await json_probe_session.exec(
            _json_probe.insert().values(id=1, payload_jsonb={"task": "restore-weekly"})
        )
        await json_probe_session.commit()

        result = await json_probe_session.exec(
            select(func_json_extract(name, _json_probe.c.payload_jsonb, "task"))
        )
        assert result.scalar_one() == "restore-weekly"

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_text_column_casts_to_json_before_extract(
        self, json_probe_session: AsyncSession
    ):
        """Execute ``CAST(text AS JSON) ->> key`` so the text-column regression bites.

        Without the cast PostgreSQL raises ``operator does not exist: text ->>
        unknown`` at execution time — the exact failure that shipped in production
        for ``celery_periodictask.kwargs``. Asserting on the returned scalar turns
        that execution-time error into a test failure, which the compile-only
        siblings cannot.
        """
        name = json_probe_session.get_bind().name
        await json_probe_session.exec(
            _json_probe.insert().values(
                id=1, payload_text='{"task_name": "backup-daily"}'
            )
        )
        await json_probe_session.commit()

        result = await json_probe_session.exec(
            select(func_json_extract(name, _json_probe.c.payload_text, "task_name"))
        )
        assert result.scalar_one() == "backup-daily"

    @pytest.mark.postgres
    @pytest.mark.asyncio
    async def test_auto_json_column_extracts_scalar(
        self, postgres_session: AsyncSession
    ):
        """Execute the arrow chain against a real ``AutoJSON`` (``jsonb``) column.

        ``TaskHistory.execution_request`` is ``TaskExecutionRequestJSON``, an
        ``AutoJSON`` ``TypeDecorator`` that resolves to ``jsonb`` on PostgreSQL.
        The helper must unwrap the decorator and emit the index-compatible arrow
        chain with no spurious ``CAST``; executing it against a stored row proves
        the unwrap is correct end-to-end.
        """
        task = await TaskManager.create(
            postgres_session,
            TaskWrite.model_validate(TaskFactory.build(name="mysqldump")),
        )
        await TaskHistoryManager.save(postgres_session, build_task_history(task))
        name = postgres_session.get_bind().name

        result = await postgres_session.exec(
            select(func_json_extract(name, col(TaskHistory.execution_request), "task"))
        )
        assert result.scalar_one() == "mysqldump"


_SQLALCHEMY_DEFAULT_POOL_SIZE = 5
_SQLALCHEMY_DEFAULT_MAX_OVERFLOW = 10


class TestCreateAppAsyncEngine:
    """Exercise the ``create_app_async_engine`` shared factory."""

    @staticmethod
    def _postgres_options(**overrides) -> DatabaseOptions:
        """Return a lazy PostgreSQL ``DatabaseOptions`` (never connects until used)."""
        return DatabaseOptions(
            ENGINE=AsyncDatabaseEngine.POSTGRESQL,
            HOST="localhost",
            PORT=5432,
            USER="u",
            PASSWORD="p",
            NAME="db",
            **overrides,
        )

    @pytest.mark.asyncio
    async def test_forwards_set_pool_options(self):
        """Forward set pool fields into the async engine's pool."""
        pool = {"POOL_SIZE": 7, "MAX_OVERFLOW": 3, "POOL_TIMEOUT": 25.0}
        engine = create_app_async_engine(self._postgres_options(**pool))
        try:
            assert engine.pool.size() == pool["POOL_SIZE"]
            assert engine.pool._max_overflow == pool["MAX_OVERFLOW"]
            assert engine.pool._timeout == pool["POOL_TIMEOUT"]
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_preserves_sqlalchemy_defaults_when_unset(self):
        """Preserve SQLAlchemy's own defaults when pool fields are unset."""
        engine = create_app_async_engine(self._postgres_options())
        try:
            assert engine.pool.size() == _SQLALCHEMY_DEFAULT_POOL_SIZE
            assert engine.pool._max_overflow == _SQLALCHEMY_DEFAULT_MAX_OVERFLOW
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_pre_pings_by_default(self):
        """Enable pool_pre_ping on the async engine when unset."""
        engine = create_app_async_engine(self._postgres_options())
        try:
            assert engine.pool._pre_ping is True
        finally:
            await engine.dispose()

    @pytest.mark.asyncio
    async def test_respects_pre_ping_opt_out(self):
        """Disable pool_pre_ping when POOL_PRE_PING is false."""
        engine = create_app_async_engine(self._postgres_options(POOL_PRE_PING=False))
        try:
            assert engine.pool._pre_ping is False
        finally:
            await engine.dispose()

    def test_forwards_connect_args_when_set(self, monkeypatch: pytest.MonkeyPatch):
        """Forward dialect-mapped connect_args into create_async_engine."""
        recorded: dict[str, object] = {}
        engine = MagicMock()

        def _fake_create(*_args, **kwargs):
            recorded.update(kwargs)
            return engine

        monkeypatch.setattr("app.core.db.utils.create_async_engine", _fake_create)

        create_app_async_engine(self._postgres_options(CONNECT_TIMEOUT=2.5))

        assert recorded["connect_args"] == {"timeout": 2.5}

    def test_omits_connect_args_when_unset(self, monkeypatch: pytest.MonkeyPatch):
        """Pass no connect_args kwarg when CONNECT_TIMEOUT is unset."""
        recorded: dict[str, object] = {}
        engine = MagicMock()

        def _fake_create(*_args, **kwargs):
            recorded.update(kwargs)
            return engine

        monkeypatch.setattr("app.core.db.utils.create_async_engine", _fake_create)

        create_app_async_engine(self._postgres_options())

        assert "connect_args" not in recorded

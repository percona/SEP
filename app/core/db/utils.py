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

"""Define database utilities."""

import re
from collections.abc import Iterable
from typing import Any

from alembic.runtime.migration import MigrationContext
from sqlalchemy import (
    cast,
    Column,
    ColumnClause,
    ColumnElement,
    func,
    inspect,
    JSON,
    literal,
    String,
    Text,
    text,
    TypeDecorator,
)
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker
from sqlalchemy.sql import coercions, ColumnExpressionArgument, roles
from sqlalchemy.sql.compiler import SQLCompiler
from sqlalchemy.sql.dml import Insert as GenericInsert
from sqlalchemy.sql.type_api import TypeEngine
from sqlalchemy.sql.visitors import InternalTraversal
from sqlmodel import AutoString, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.config import DatabaseOptions
from app.core.db.sql_types import AutoJSON
from app.core.utils.fields import DatabaseDialect
from app.core.utils.serialization import json_serializer

SQLAlchemyColumn = ColumnClause | Column | InstrumentedAttribute


def get_async_session_maker_from_engine(engine: AsyncEngine) -> async_sessionmaker:
    """Return a new asynchronous session maker for database operations.

    This function creates a new SQLAlchemy asynchronous session maker using the
    predefined engine configuration.

    :param engine: The SQLAlchemy asynchronous engine to bind the session maker to.
    :type engine: AsyncEngine
    :return: A new asynchronous session maker.
    :rtype: async_sessionmaker
    """
    return sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def create_app_async_engine(database: DatabaseOptions) -> AsyncEngine:
    """Build a service API async engine, forwarding only the set pool options.

    Unset pool fields are omitted so the engine keeps SQLAlchemy's own defaults,
    leaving standalone deployments unchanged. An unset or SQLite-inapplicable
    ``CONNECT_TIMEOUT`` likewise omits ``connect_args`` entirely.

    :param database: The service database options carrying the URL and any
        configured pool sizing.
    :return: A configured asynchronous engine.
    """
    return create_async_engine(
        database.URL,
        echo=False,
        json_serializer=json_serializer,
        **database.connect_engine_kwargs,
        **database.pool_engine_kwargs,
    )


def json_join_path_elems(*path_elems: str) -> str:
    """Join JSON path elements into a single string.

    :param path_elems: The JSON path elements to join.
    :type path_elems: str
    :return: The joined JSON path string.
    :rtype: str
    """
    json_path = "$"
    for elem in path_elems:
        if elem.isdigit():
            json_path += f"[{elem}]"
        else:
            json_path += f".{elem}"
    return json_path


def _column_resolves_to_json(column: ColumnElement) -> bool:
    """Return True when the column's declared SQLAlchemy type is JSON-semantic.

    Unwrap ``TypeDecorator`` chains so columns typed with ``AutoJSON`` (or
    subclasses like ``TaskExecutionRequestJSON``) are recognised as JSON via
    their ``impl`` type and do not receive a redundant ``CAST(... AS JSON)``
    wrapper that would break expression-index matches on ``jsonb`` columns.

    :param column: The SQLAlchemy column element to inspect.
    :type column: ColumnElement
    :return: ``True`` if the column resolves to ``JSON`` or ``JSONB`` (directly
        or through a ``TypeDecorator`` chain), ``False`` otherwise.
    :rtype: bool
    """
    type_obj = column.type
    while isinstance(type_obj, TypeDecorator):
        type_obj = type_obj.impl_instance
    return isinstance(type_obj, JSON)


def func_json_extract(
    db_engine: str, json_column: SQLAlchemyColumn, *path_elems: str
) -> ColumnElement:
    """Render a dialect-specific JSON scalar extraction expression.

    Emit SQL whose shape matches the expression indexes created for
    ``taskhistory.execution_request`` so the planner can use them:

    - PostgreSQL: ``col->'a'->>'b'``. The final ``->>`` returns the value as
      text. The expression is valid on both ``json`` and ``jsonb`` columns.
      Path elements are inlined as SQL literals (via SQLAlchemy's
      ``literal_execute``) instead of bound parameters so the planner can
      syntactically match the expression against the functional indexes.
      Columns whose declared type is not JSON-semantic (e.g.
      ``celery_periodictask.kwargs`` which the third-party
      ``sqlalchemy-celery-beat`` library defines as ``sa.Text()``) are wrapped
      in ``CAST(... AS JSON)`` first, because PostgreSQL does not define
      ``->>`` on ``text``. JSON, JSONB, and ``TypeDecorator`` chains whose
      underlying impl is JSON (e.g. ``AutoJSON``) are left unwrapped so their
      expression indexes keep matching.
    - SQLite: ``json_extract(col, '$.a.b')``. SQLite auto-unquotes scalars, so
      the result is directly comparable to a string.
    - MySQL: ``json_extract(col, '$.a.b')``. No functional index is created on
      MySQL because a width-limited ``CAST`` would introduce comparison
      truncation; MySQL dev environments fall back to non-indexed filtering.

    :param db_engine: The database engine type (e.g., ``"postgresql"``).
    :type db_engine: str
    :param json_column: The JSON column to extract the value from.
    :type json_column: SQLAlchemyColumn
    :param path_elems: The JSON path elements to extract.
    :type path_elems: str
    :return: A SQL expression whose value is comparable to a string.
    :rtype: ColumnElement
    """
    column = col(json_column)
    if db_engine.startswith(DatabaseDialect.POSTGRESQL):
        expression = column if _column_resolves_to_json(column) else cast(column, JSON)
        for elem in path_elems[:-1]:
            expression = expression.op("->")(literal(elem, Text, literal_execute=True))
        return expression.op("->>", return_type=Text)(
            literal(path_elems[-1], Text, literal_execute=True)
        )
    return func.json_extract(
        column,
        literal(json_join_path_elems(*path_elems), Text, literal_execute=True),
    )


def idempotent_insert(engine_name: str, table: Any) -> GenericInsert:
    """Return a dialect-specific INSERT that ignores duplicate-key conflicts.

    PostgreSQL and SQLite use ``INSERT ... ON CONFLICT DO NOTHING``; MySQL uses
    ``INSERT IGNORE ...``. The caller chains ``.values(...)`` and passes the
    result to ``session.execute``.

    :param engine_name: SQLAlchemy engine ``name`` (``"postgresql"``, ``"sqlite"``,
        or ``"mysql"``).
    :type engine_name: str
    :param table: The target table or ORM model class.
    :type table: Any
    :return: A dialect-specific insert construct.
    :rtype: GenericInsert
    :raises NotImplementedError: If the dialect is not supported.
    """
    if engine_name == DatabaseDialect.POSTGRESQL:
        return postgresql.insert(table).on_conflict_do_nothing()
    if engine_name == DatabaseDialect.SQLITE:
        return sqlite.insert(table).on_conflict_do_nothing()
    if engine_name == DatabaseDialect.MYSQL:
        return mysql.insert(table).prefix_with("IGNORE")
    raise NotImplementedError(f"idempotent_insert: unsupported dialect {engine_name!r}")


class NullsLastOrdering(ColumnElement):
    """Render an ``ORDER BY`` term that places NULLs last on every supported dialect.

    PostgreSQL and SQLite render the standard ``NULLS LAST`` clause. MySQL has no
    such syntax, so its hook prepends ``ISNULL(<expr>) ASC`` -- ``ISNULL`` yields
    ``1`` for NULL and ``0`` otherwise, pinning NULLs last independently of the
    primary direction.

    Takes the direction as a flag rather than a pre-directed expression: wrapping an
    already-``desc()``-ed expression would make the MySQL hook emit the invalid
    ``ISNULL(<expr> DESC)``.

    Participates in SQLAlchemy's compiled-statement cache, with a key that
    discriminates both column and direction.

    :param column: The direction-free column expression to order by.
    :param descending: Whether the primary ordering term is descending.
    """

    _traverse_internals: list[tuple[str, InternalTraversal]] = [
        ("column", InternalTraversal.dp_clauseelement),
        ("descending", InternalTraversal.dp_boolean),
    ]

    def __init__(
        self,
        column: ColumnExpressionArgument,
        *,
        descending: bool = False,
    ) -> None:
        self.column = coercions.expect(roles.ExpressionElementRole, column)
        self.descending = descending


@compiles(NullsLastOrdering)
def _compile_nulls_last_ordering(
    element: NullsLastOrdering, compiler: SQLCompiler, **kw: Any
) -> str:
    """Render the standard ``<expr> <direction> NULLS LAST`` ordering term.

    :param element: The ordering construct being compiled.
    :param compiler: The active SQL compiler.
    :return: The rendered ``ORDER BY`` term.
    """
    direction = "DESC" if element.descending else "ASC"
    return f"{compiler.process(element.column, **kw)} {direction} NULLS LAST"


@compiles(NullsLastOrdering, DatabaseDialect.MYSQL)
def _compile_nulls_last_ordering_mysql(
    element: NullsLastOrdering, compiler: SQLCompiler, **kw: Any
) -> str:
    """Render MySQL's ``ISNULL(<expr>) ASC, <expr> <direction>`` equivalent.

    The interpolated text is the compiler's own rendering of the wrapped
    expression, never a client-supplied value: sort keys are allowlisted by
    :attr:`~app.core.db.list_query.ListQuerySpec.sortable` before they reach the
    construct, and :class:`NullsLastOrdering` coerces a raw string argument into a
    bound parameter rather than SQL text. Path literals carried by
    :func:`func_json_extract` use ``literal_execute``, so the dialect's literal
    processor inlines them at execution -- the same rendering that function
    documents, unchanged by the wrapper.

    :param element: The ordering construct being compiled.
    :param compiler: The active SQL compiler.
    :return: The rendered pair of ``ORDER BY`` terms.
    """
    rendered = compiler.process(element.column, **kw)
    direction = "DESC" if element.descending else "ASC"
    return f"ISNULL({rendered}) ASC, {rendered} {direction}"


def prepare_unsafe_value_for_json_comparison(db_engine: str, value: Any) -> Any:
    """Prepare a value for JSON comparison based on the database engine.

    On PostgreSQL the text operator ``->>`` returns JSON scalars as text, so we
    convert the value to a string for comparison. For other databases, we return
    the value as is.

    :param db_engine: The database engine type (e.g., "postgresql").
    :type db_engine: str
    :param value: The value to prepare for comparison.
    :type value: Any
    :return: The prepared value for JSON comparison.
    :rtype: Any
    """
    if db_engine.startswith(DatabaseDialect.POSTGRESQL):
        return str(value)
    return value


def compare_type(
    context: MigrationContext,  # noqa: ARG001
    inspected_column: Column,  # noqa: ARG001
    metadata_column: Column,  # noqa: ARG001
    inspected_type: TypeEngine,
    metadata_type: TypeEngine,
) -> bool | None:
    """Suppress spurious Alembic type diffs for known equivalent type pairs.

    :param context: The Alembic migration context.
    :type context: MigrationContext
    :param inspected_column: The column object as inspected from the database.
    :type inspected_column: Column
    :param metadata_column: The column object as defined in the model's metadata.
    :type metadata_column: Column
    :param inspected_type: The type of the column as determined by the database
        inspector.
    :type inspected_type: TypeEngine
    :param metadata_type: The type of the column as defined in the model's metadata.
    :type metadata_type: TypeEngine
    :return: False if the types are equivalent and no migration is needed;
        None to fall through to default comparison.
    :rtype: bool | None
    """
    if isinstance(inspected_type, Text) and isinstance(metadata_type, AutoString):
        return False
    if isinstance(metadata_type, AutoJSON) and isinstance(inspected_type, JSONB | JSON):
        return False
    if (
        isinstance(metadata_type, TypeDecorator)
        and isinstance(inspected_type, String)
        and isinstance(metadata_type.impl, String)
    ):
        return False if inspected_type.length == metadata_type.impl.length else None
    return None


def acquire_pg_advisory_xact_lock(bind: Connection, lock_key: int) -> None:
    """Serialize concurrent shared-database migrations on PostgreSQL.

    Take a transaction-scoped advisory lock so two service tracks running
    ``upgrade heads`` against one physical database cannot both pass an
    idempotency preflight and execute the same DDL simultaneously. The lock
    releases automatically at transaction end. No-op on other dialects: SQLite
    and per-service-database deployments give each service its own database, so
    there is no cross-track race to serialize.

    :param bind: The migration's bound connection (``op.get_bind()``).
    :param lock_key: The advisory-lock key; all callers racing on the same
        object must pass the same key.
    """
    if bind.dialect.name == DatabaseDialect.POSTGRESQL:
        bind.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key})


def table_exists(bind: Connection, table_name: str) -> bool:
    """Return whether ``table_name`` is present on the bound database.

    Enum-widening downgrades need this as a separate preflight from
    :func:`check_constraint_lists_members`. That helper collapses "the table is
    gone" and "the member is not listed" into a single ``False``, which reads
    correctly for a narrowing guard (``if not lists_members: return``) but
    inverts for a widening one (``if lists_members: return``) — there, a missing
    table falls through into DDL against a table another track already dropped.

    :param bind: The migration's bound connection (``op.get_bind()``).
    :param table_name: The table to test for.
    :return: ``True`` when the table exists.
    """
    return inspect(bind).has_table(table_name)


def _check_constraints_for_column(
    bind: Connection,
    table_name: str,
    column_name: str,
) -> list[dict[str, Any]]:
    """Return CHECK constraints whose SQL text mentions ``column_name``.

    :param bind: The migration's bound connection (``op.get_bind()``).
    :param table_name: The table whose CHECK constraints are inspected.
    :param column_name: The constrained column, used to select the relevant
        constraint and avoid matching unrelated CHECKs.
    :return: Matching inspector constraint dicts, or an empty list when the
        table does not exist.
    """
    inspector = inspect(bind)
    if not inspector.has_table(table_name):
        return []
    return [
        constraint
        for constraint in inspector.get_check_constraints(table_name)
        if column_name in (constraint["sqltext"] or "")
    ]


def check_constraint_name(
    bind: Connection,
    table_name: str,
    column_name: str,
) -> str | None:
    """Return the name of the CHECK constraint on ``column_name``, if any.

    Used by the SEP-1825 constraint-drop migrations so a second track on a
    shared PostgreSQL database can no-op once the first track has already
    dropped ``settingoverride.setting_class``'s CHECK.

    :param bind: The migration's bound connection (``op.get_bind()``).
    :param table_name: The table whose CHECK constraints are inspected.
    :param column_name: The constrained column.
    :return: The constraint name, or ``None`` when the table or constraint is
        absent.
    """
    constraints = _check_constraints_for_column(bind, table_name, column_name)
    if not constraints:
        return None
    return constraints[0].get("name")


def check_constraint_lists_members(
    bind: Connection,
    table_name: str,
    column_name: str,
    members: Iterable[str],
) -> bool:
    """Return ``True`` when the CHECK constraint on ``column_name`` lists every member.

    Until SEP-1825 dropped it, the ``setting_class`` column used
    ``native_enum=False``, so its allowed values lived in a ``CHECK`` constraint
    rather than a PostgreSQL ``TYPE``. This reflects the constraint text
    cross-dialect via ``sqlalchemy.inspect`` and tests membership by matching
    each value as a single-quoted SQL string literal, so ``"SETTINGS"`` does not
    spuriously match ``"SEP_SETTINGS"``. Historical enum-extension migrations
    and the SEP-1825 downgrade still consult this helper.

    Returns ``False`` when the table does not exist. ``get_check_constraints``
    raises ``NoSuchTableError`` for a missing table, and a missing table means
    there is no constraint to list anything.

    That single ``False`` carries two meanings, so it only short-circuits DDL
    for a guard written ``if not lists_members: return`` (enum widening on
    upgrade, narrowing on downgrade). A guard with the opposite polarity —
    ``if lists_members: return``, as enum *narrowing* needs on upgrade and its
    widening downgrade needs in reverse — falls through on a missing table and
    runs DDL against it. Those call sites must precede this check with
    :func:`table_exists`.

    :param bind: The migration's bound connection (``op.get_bind()``).
    :param table_name: The table whose CHECK constraints are inspected.
    :param column_name: The constrained column, used to select the relevant
        constraint and avoid matching unrelated CHECKs.
    :param members: The enum member names to test for.
    :return: ``True`` only if the table exists and every member appears as a
        quoted literal in a CHECK constraint referencing ``column_name``.
    """
    haystack = " ".join(
        constraint["sqltext"] or ""
        for constraint in _check_constraints_for_column(bind, table_name, column_name)
    )
    return bool(haystack) and all(
        re.search(rf"'{re.escape(member)}'", haystack) for member in members
    )

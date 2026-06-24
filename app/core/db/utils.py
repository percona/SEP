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
    Text,
    text,
    TypeDecorator,
)
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncEngine
from sqlalchemy.orm import InstrumentedAttribute, sessionmaker
from sqlalchemy.sql.dml import Insert as GenericInsert
from sqlalchemy.sql.type_api import TypeEngine
from sqlmodel import AutoString, col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.sql_types import AutoJSON
from app.core.utils.fields import DatabaseDialect

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


def check_constraint_lists_members(
    bind: Connection,
    table_name: str,
    column_name: str,
    members: Iterable[str],
) -> bool:
    """Return ``True`` when the CHECK constraint on ``column_name`` lists every member.

    The ``setting_class`` column uses ``native_enum=False``, so its allowed
    values live in a ``CHECK`` constraint rather than a PostgreSQL ``TYPE``. This
    reflects the constraint text cross-dialect via ``sqlalchemy.inspect`` and
    tests membership by matching each value as a single-quoted SQL string
    literal, so ``"SETTINGS"`` does not spuriously match ``"SEP_SETTINGS"``.

    Returns ``False`` when the table does not exist -- ``get_check_constraints``
    raises ``NoSuchTableError`` for a missing table, and a missing table means
    there is no constraint to list anything (so an enum-narrowing downgrade
    correctly no-ops when another track already dropped the shared table).

    :param bind: The migration's bound connection (``op.get_bind()``).
    :param table_name: The table whose CHECK constraints are inspected.
    :param column_name: The constrained column, used to select the relevant
        constraint and avoid matching unrelated CHECKs.
    :param members: The enum member names to test for.
    :return: ``True`` only if the table exists and every member appears as a
        quoted literal in a CHECK constraint referencing ``column_name``.
    """
    inspector = inspect(bind)
    if not inspector.has_table(table_name):
        return False
    haystack = " ".join(
        constraint["sqltext"] or ""
        for constraint in inspector.get_check_constraints(table_name)
        if column_name in (constraint["sqltext"] or "")
    )
    return all(re.search(rf"'{re.escape(member)}'", haystack) for member in members)

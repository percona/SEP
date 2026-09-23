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

"""Define database operations for the MySQL backup catalog."""

from collections.abc import Iterable, Sequence
from typing import Any, cast

from sqlalchemy import case, func, Integer, literal, or_, select, String, union_all
from sqlalchemy.sql import ColumnElement, ColumnExpressionArgument, Subquery
from sqlmodel import and_, col
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.sql.expression import Select as SQLModelSelect

from app.core.db.crud import BaseSQLModelManager
from app.core.db.utils import NullsLastOrdering
from app.core.pagination import PaginatedResponse, Pagination
from app.sep.apps.mysql_backups.models import (
    BACKUP_PATH_STRIP_CHARS,
    CatalogServiceKey,
    CataloguedSourceTransport,
    MysqlBackupRun,
)

#: Prefetch key ``(service_id, service_name, backup_source)`` used by restore list.
CatalogTransportLookupKey = tuple[int | None, str, str]

_NEWEST_RUN_FIRST = (
    NullsLastOrdering(col(MysqlBackupRun.finished_at), descending=True),
    col(MysqlBackupRun.created_at).desc(),
    col(MysqlBackupRun.id).desc(),
)


def _sql_strip(column: Any) -> ColumnElement[str | None]:
    """Strip leading/trailing ASCII whitespace the way :func:`strip_backup_path` does.

    ``ltrim`` / ``rtrim`` with :data:`~app.sep.apps.mysql_backups.models.BACKUP_PATH_STRIP_CHARS`
    work on both PostgreSQL and SQLite; plain ``TRIM`` would leave tabs and
    newlines in place. Unicode separators (NBSP, …) are intentionally left
    alone — the same contract as the Python helper — so a catalog key and this
    expression always agree.

    ``column`` is typed as :data:`~typing.Any` because ``sqlmodel.col`` yields
    ``Mapped[...]`` at the call site while SQLAlchemy's ``ltrim``/``rtrim``
    accept a ``ColumnElement``.

    :param column: The text column to strip.
    :return: The stripped column expression.
    """
    return cast(
        ColumnElement[str | None],
        func.rtrim(
            func.ltrim(column, BACKUP_PATH_STRIP_CHARS), BACKUP_PATH_STRIP_CHARS
        ),
    )


def _preferred_backup_source_expr() -> ColumnElement[str | None]:
    """Return the SQL expression mirroring :func:`preferred_backup_source`.

    Prefer a non-blank ASCII-stripped ``upload_destination``, else a non-blank
    ASCII-stripped ``location``. Stripping uses
    :data:`~app.sep.apps.mysql_backups.models.BACKUP_PATH_STRIP_CHARS` (not SQL
    ``TRIM``, not Unicode ``str.strip``) so the catalog lookup keys on the same
    string
    :func:`~app.sep.apps.mysql_backups.backup_source_choices.backup_run_to_choice`
    offers a restore form.

    :return: The preferred-source column expression.
    """
    upload = col(MysqlBackupRun.upload_destination)
    location = col(MysqlBackupRun.location)
    upload_stripped = _sql_strip(upload)
    location_stripped = _sql_strip(location)
    return cast(
        ColumnElement[str | None],
        case(
            (and_(upload.is_not(None), upload_stripped != ""), upload_stripped),
            (and_(location.is_not(None), location_stripped != ""), location_stripped),
        ),
    )


def _matches_preferred_source(
    backup_source: str,
) -> ColumnExpressionArgument[bool]:
    """Return a WHERE clause comparing the preferred source to ``backup_source``.

    :param backup_source: The restore body's preferred-source string to match.
    :return: The SQL predicate for :meth:`BaseSQLModelManager.list`.
    """
    return cast(
        ColumnExpressionArgument[bool],
        _preferred_backup_source_expr() == backup_source,
    )


def _catalog_transport_lookup_subquery(
    pending: Sequence[CatalogTransportLookupKey],
) -> Subquery:
    """Build a portable subquery of ``(service_id, service_name, backup_source)`` rows.

    Uses ``UNION ALL`` of labeled literals rather than ``VALUES (...) AS alias
    (cols)``, which PostgreSQL accepts but SQLite rejects with a syntax error
    near the column-list parentheses.

    :param pending: Non-empty lookup keys to materialise as rows.
    :return: A subquery selectable with ``lk_service_id``, ``lk_service_name``,
        and ``lk_backup_source`` columns.
    """
    rows = [
        select(
            literal(service_id, Integer).label("lk_service_id"),
            literal(service_name, String).label("lk_service_name"),
            literal(backup_source, String).label("lk_backup_source"),
        )
        for service_id, service_name, backup_source in pending
    ]
    return union_all(*rows).subquery("catalog_transport_lookups")


class MysqlBackupRunManager(BaseSQLModelManager):
    """Manage :class:`MysqlBackupRun` CRUD operations.

    :cvar Model: The SQLModel class this manager is responsible for
        (``MysqlBackupRun``).
    """

    Model = MysqlBackupRun

    @classmethod
    def _service_match(
        cls,
        service_id: ColumnElement[Any],
        service_name: ColumnElement[Any],
    ) -> ColumnExpressionArgument[bool]:
        """Return a predicate matching catalog rows to a service id/name pair.

        A null ``service_id`` matches by name only. A non-null id matches that id
        or a name-only legacy row (``service_id IS NULL``), so two same-named
        inventory services stay apart while pre-id catalog rows still resolve.
        Used for both a single :class:`CatalogServiceKey` (literals) and the
        batched lookup join (lookup-subquery columns).

        :param service_id: Lookup-side service id expression (column or literal).
        :param service_name: Lookup-side service name expression (column or literal).
        :return: The SQL predicate against :class:`MysqlBackupRun` columns.
        """
        run_id = col(MysqlBackupRun.service_id)
        run_name = col(MysqlBackupRun.service_name)
        by_name = run_name == service_name
        return cast(
            ColumnExpressionArgument[bool],
            or_(
                and_(service_id.is_(None), by_name),
                and_(
                    service_id.is_not(None),
                    or_(
                        run_id == service_id,
                        and_(run_id.is_(None), by_name),
                    ),
                ),
            ),
        )

    @classmethod
    def _service_predicate(
        cls, key: CatalogServiceKey
    ) -> ColumnExpressionArgument[bool]:
        """Return the predicate selecting one service's rows.

        When an id is known, the name is matched only for rows carrying *no* id —
        guarding that fallback on ``IS NULL`` is what keeps two same-named services
        apart, since ``Service.name`` carries no uniqueness constraint and an
        unguarded name match would hand each service the other's runs.

        A key with no id (free-typed destination with no inventory row) has only
        the name to match on, so it matches every row recorded under that name
        regardless of whether those rows carry an id.

        :param key: The service name and optional inventory id to select rows by.
        :return: The SQL predicate selecting this service's rows.
        """
        return cls._service_match(
            literal(key.service_id, Integer),
            literal(key.service_name, String),
        )

    @classmethod
    async def referenced_service_ids(cls, session: AsyncSession) -> set[int]:
        """Return every inventory service id the catalog still points at.

        The catalog resolves these ids on a client-facing route, so collecting
        one would turn a documented historical read into a 404. The query lives
        here rather than in the collector because the column is this app's.

        :param session: The asynchronous SEP database session.
        :return: The distinct service ids recorded on backup runs.
        """
        return set(
            await cls.values_list(
                session,
                ["service_id"],
                col(MysqlBackupRun.service_id).is_not(None),
            )
        )

    @classmethod
    async def list_for_service(
        cls,
        session: AsyncSession,
        key: CatalogServiceKey,
        *,
        pagination: Pagination,
    ) -> PaginatedResponse[MysqlBackupRun]:
        """Return a page of a service's recorded backup runs, newest run first.

        Keyed by :meth:`_service_predicate`. The reported total counts exactly the
        rows this query can return, so a caller paging to a fixed cap is never cut
        short by a total drawn from a wider key.

        Ordered by run completion (``finished_at`` desc), not insertion time, so
        a run that was catalogued late cannot jump ahead of a more recently
        finished one. NULLs-last is explicit via
        :class:`~app.core.db.utils.NullsLastOrdering`, so a row whose
        ``finished_at`` was never reported sorts to the tail on every supported
        backend, including MySQL, which has no native ``NULLS LAST`` syntax.
        ``created_at`` then ``id`` (both desc) break ties and order the
        null-``finished_at`` rows among themselves by insertion order.

        :param session: The database session to query on.
        :param key: The service the records are selected for.
        :param pagination: Validated offset/limit window for this page.
        :return: The requested page of the service's backup-run records, newest
            run first.
        """
        return await cls.list_paginated(
            session,
            cls._service_predicate(key),
            order_by=list(_NEWEST_RUN_FIRST),
            pagination=pagination,
        )

    @classmethod
    async def list_for_history_ids(
        cls,
        session: AsyncSession,
        history_ids: Sequence[int],
        *,
        pagination: Pagination,
    ) -> PaginatedResponse[MysqlBackupRun]:
        """Return a page of the runs recorded for ``history_ids``, newest first.

        Ordered identically to :meth:`list_for_service` so the task-scoped and
        service-scoped views of one run agree.

        An empty ``history_ids`` — the ordinary answer for a task that has not
        succeeded yet — is answered without a query: an empty ``IN`` renders as a
        degenerate always-false predicate, and short-circuiting makes ``total``
        zero by construction rather than by the page and count queries agreeing.

        :param session: The session to query through.
        :param history_ids: The task-history ids to select catalog rows for.
        :param pagination: Validated offset/limit window for this page.
        :return: A page of matching runs, newest finished run first.
        """
        if not history_ids:
            return PaginatedResponse.from_pagination([], 0, pagination)
        return await cls.list_paginated(
            session,
            col(MysqlBackupRun.task_history_id).in_(history_ids),
            order_by=list(_NEWEST_RUN_FIRST),
            pagination=pagination,
        )

    @classmethod
    async def newest_for_backup_source(
        cls,
        session: AsyncSession,
        key: CatalogServiceKey,
        backup_source: str,
    ) -> MysqlBackupRun | None:
        """Return the newest run whose catalog-computed source matches ``backup_source``.

        Scoped by :meth:`_service_predicate` and ordered like
        :meth:`list_for_service`. The match key is the preferred source
        (``upload_destination`` when set, else ``location``), the same string
        :func:`~app.sep.apps.mysql_backups.models.preferred_backup_source`
        computes — never a raw field equality. Only the single newest match is
        considered; older matching rows are ignored.

        :param session: The database session to query on.
        :param key: The service the records are selected for.
        :param backup_source: The restore body's ``backup_source`` to match.
        :return: The newest matching catalog row, or ``None`` when none match.
        """
        if not backup_source:
            return None
        matches = await cls.list(
            session,
            cls._service_predicate(key),
            _matches_preferred_source(backup_source),
            order_by=list(_NEWEST_RUN_FIRST),
            limit=1,
        )
        return matches[0] if matches else None

    @classmethod
    async def catalogued_source_transport(
        cls,
        session: AsyncSession,
        key: CatalogServiceKey,
        backup_source: str,
    ) -> CataloguedSourceTransport | None:
        """Return the recorded object-store transport for a matching run, if any.

        Looks up :meth:`newest_for_backup_source` and returns that row's
        ``source_transport`` when set (S3/GCS). A miss, a location-only run, or a
        row written before the column existed all yield ``None`` so the caller
        falls back to inference.

        :param session: The database session to query on.
        :param key: The service the records are selected for.
        :param backup_source: The restore body's ``backup_source`` to match.
        :return: The catalogued transport, or ``None`` when unavailable.
        """
        run = await cls.newest_for_backup_source(session, key, backup_source)
        return run.source_transport if run is not None else None

    @classmethod
    async def catalogued_source_transports(
        cls,
        session: AsyncSession,
        lookups: Iterable[CatalogTransportLookupKey],
    ) -> dict[CatalogTransportLookupKey, CataloguedSourceTransport | None]:
        """Return catalogued transports for many preferred-source keys in one query.

        Used by the restore list/detail prefetch so a page of undeclared stamps
        pays one SELECT instead of one per key. Each lookup is scoped by the same
        :meth:`_service_predicate` / preferred-source rules as
        :meth:`catalogued_source_transport`, with service id/name taken from the
        lookup tuple itself. Ranking happens in SQL (``row_number`` partitioned
        by lookup key, ordered like :meth:`list_for_service`) so only the newest
        matching row per key is materialised — stable destinations such as
        ``s3://bucket/service`` do not pull every historical run into memory.
        Empty ``backup_source`` keys and misses map to ``None``.

        :param session: The database session to query on.
        :param lookups: Prefetch keys ``(service_id, service_name, backup_source)``.
        :return: The same keys mapped to a catalogued transport or ``None``.
        """
        results: dict[CatalogTransportLookupKey, CataloguedSourceTransport | None] = {}
        pending: list[CatalogTransportLookupKey] = []
        for cache_key in lookups:
            if not cache_key[2]:
                results[cache_key] = None
            else:
                pending.append(cache_key)
        if not pending:
            return results

        lookup_values = _catalog_transport_lookup_subquery(pending)
        service_match = cls._service_match(
            lookup_values.c.lk_service_id,
            lookup_values.c.lk_service_name,
        )
        ranked = (
            select(
                lookup_values.c.lk_service_id,
                lookup_values.c.lk_service_name,
                lookup_values.c.lk_backup_source,
                col(MysqlBackupRun.source_transport).label("source_transport"),
                func.row_number()
                .over(
                    partition_by=(
                        lookup_values.c.lk_service_id,
                        lookup_values.c.lk_service_name,
                        lookup_values.c.lk_backup_source,
                    ),
                    order_by=_NEWEST_RUN_FIRST,
                )
                .label("rn"),
            )
            .join_from(
                MysqlBackupRun,
                lookup_values,
                and_(
                    service_match,
                    _preferred_backup_source_expr() == lookup_values.c.lk_backup_source,
                ),
            )
            .subquery("ranked_catalog_transports")
        )
        # ``sqlalchemy.select`` of bare columns is not a sqlmodel ``Select``, so
        # cast into the shape ``BaseManager._exec``'s overload accepts. Runtime
        # execution is unchanged.
        query = cast(
            SQLModelSelect[Any],
            select(
                ranked.c.lk_service_id,
                ranked.c.lk_service_name,
                ranked.c.lk_backup_source,
                ranked.c.source_transport,
            ).where(ranked.c.rn == 1),
        )

        results.update(dict.fromkeys(pending, None))
        for row in (await cls._exec(session, query)).all():
            results[(row.lk_service_id, row.lk_service_name, row.lk_backup_source)] = (
                row.source_transport
            )
        return results

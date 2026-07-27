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

"""Define database operations for Snippets."""

from typing import Any

from sqlalchemy import ColumnElement, func, or_
from sqlalchemy.sql import ColumnExpressionArgument
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.core.db.utils import func_json_extract
from app.core.pagination import PaginatedResponse, Pagination
from app.sep.snippets.list_query import (
    SNIPPET_SORT_KEYS,
    SnippetApprovalFilter,
    SnippetListQuery,
    SnippetSortColumn,
    SnippetSortDirection,
    TIE_BREAKER_COLUMN,
)
from app.sep.snippets.models import Snippet
from app.sep.snippets.models.meta import (
    META_KEY_DESCRIPTION,
    META_KEY_SERVICE_TYPE,
    META_KEY_TITLE,
)

_LIKE_ESCAPE_CHAR = "\\"


def _escape_like(term: str) -> str:
    r"""Escape LIKE wildcards so a search term matches literally.

    :param term: The raw search term.
    :return: The term with ``\``, ``%``, and ``_`` each prefixed by a backslash
        for use with ``ilike(pattern, escape="\\")``.
    """
    for char in (_LIKE_ESCAPE_CHAR, "%", "_"):
        term = term.replace(char, _LIKE_ESCAPE_CHAR + char)
    return term


class SnippetManager(BaseSQLModelManager):
    """Manage Snippet operations, including retrieval, listing, and deletion.

    :cvar Model: The SQLModel class this manager is responsible for (`Snippet`).
    :vartype Model: type[Snippet]
    :cvar ordering: The default ordering for listing snippets, first by `approved_at`
        in descending order, then by `created_at`.
    :vartype ordering: list[ColumnExpressionOrStrLabelArgument]
    """

    Model = Snippet
    ordering = [col(Snippet.approved_at).desc(), "created_at"]

    @staticmethod
    def _sort_expression(engine: str, sort_column: SnippetSortColumn) -> ColumnElement:
        """Resolve an allowlisted sort column to its backing SQL expression.

        :param engine: The database engine name (``session.get_bind().name``).
        :param sort_column: The vetted column/JSON spec from the sort allowlist.
        :return: A column expression usable in ``ORDER BY``.
        """
        if sort_column.source == "meta":
            return func_json_extract(engine, Snippet.meta, sort_column.name)
        return col(getattr(Snippet, sort_column.name))

    @staticmethod
    def _service_type_exprs(engine: str) -> tuple[ColumnElement, ColumnElement]:
        """Return the raw and trimmed ``meta.service_type`` expressions.

        The whole-dataset facet and the list filter normalise the free-form
        service type through this one definition, so a padded value groups
        identically on both paths instead of the facet and the predicate
        disagreeing on what counts as blank.

        :param engine: The database engine name (``session.get_bind().name``).
        :return: The raw JSON-extract expression and its ``TRIM``-normalised form.
        """
        raw = func_json_extract(engine, Snippet.meta, META_KEY_SERVICE_TYPE)
        return raw, func.trim(raw)

    @classmethod
    def _list_query_filters(
        cls, engine: str, list_query: SnippetListQuery
    ) -> list[ColumnExpressionArgument[bool]]:
        """Build the WHERE predicates for a snippets list query.

        Search matches the filename, title, and description case-insensitively;
        the approval and service-type filters are applied server-side. All meta-backed
        fields go through a dialect-aware JSON extract.

        :param engine: The database engine name (``session.get_bind().name``).
        :param list_query: The validated list-query selections.
        :return: The list of predicates (empty when nothing is filtered).
        """
        filters: list[ColumnExpressionArgument[bool]] = []

        if list_query.search and list_query.search.strip():
            pattern = f"%{_escape_like(list_query.search.strip())}%"
            filters.append(
                or_(
                    col(Snippet.filename).ilike(pattern, escape=_LIKE_ESCAPE_CHAR),
                    func_json_extract(engine, Snippet.meta, META_KEY_TITLE).ilike(
                        pattern, escape=_LIKE_ESCAPE_CHAR
                    ),
                    func_json_extract(engine, Snippet.meta, META_KEY_DESCRIPTION).ilike(
                        pattern, escape=_LIKE_ESCAPE_CHAR
                    ),
                )
            )

        if list_query.approval is SnippetApprovalFilter.APPROVED:
            filters.append(col(Snippet.approved_at).is_not(None))
        elif list_query.approval is SnippetApprovalFilter.NOT_APPROVED:
            filters.append(col(Snippet.approved_at).is_(None))

        service_type_raw, service_type_trimmed = cls._service_type_exprs(engine)
        if list_query.uncategorized:
            # "No service type" means absent (JSON NULL) or blank after trimming.
            filters.append(or_(service_type_raw.is_(None), service_type_trimmed == ""))
        elif list_query.service_type is not None:
            # Strip only spaces on the filter value to mirror SQL ``TRIM``'s default,
            # so the comparison agrees with the facet for tab/newline-padded values.
            filters.append(service_type_trimmed == list_query.service_type.strip(" "))

        return filters

    @classmethod
    def _list_query_order_by(
        cls, engine: str, list_query: SnippetListQuery
    ) -> list[ColumnElement]:
        """Build the deterministic ORDER BY for a snippets list query.

        The allowlisted sort key drives the primary expression; the filename column
        is appended as a unique tie-breaker so rows never shift, repeat, or drop
        across page boundaries. Sorting by filename itself is already unique, so no
        redundant second clause is added in that case.

        NULLs are pinned last regardless of direction so a sort by a meta key some
        rows lack (or the nullable ``approved_at`` column) places the same rows
        identically on SQLite and PostgreSQL, whose default NULL ordering differs.

        :param engine: The database engine name (``session.get_bind().name``).
        :param list_query: The validated list-query selections.
        :return: The ordered list of column expressions.
        """
        sort_column = SNIPPET_SORT_KEYS[list_query.sort_key]
        primary = cls._sort_expression(engine, sort_column)
        if list_query.sort_direction is SnippetSortDirection.DESC:
            primary = primary.desc()
        else:
            primary = primary.asc()
        primary = primary.nulls_last()
        tie_breaker = SnippetSortColumn("column", TIE_BREAKER_COLUMN)
        if sort_column == tie_breaker:
            return [primary]
        return [primary, col(getattr(Snippet, TIE_BREAKER_COLUMN)).asc()]

    @classmethod
    async def list_query_page(
        cls,
        session: AsyncSession,
        *,
        list_query: SnippetListQuery,
        pagination: Pagination,
    ) -> PaginatedResponse[Snippet]:
        """Return a page of snippets with server-side search, filters, and sorting.

        The count and data queries share identical predicates, so the paginated
        ``total`` matches the visible, filtered result set.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :param list_query: The validated sort/search/filter selections.
        :param pagination: The validated offset/limit window for this page.
        :return: A paginated response over the filtered, ordered snippets.
        :raises sqlalchemy.exc.SQLAlchemyError: When a count or data query fails to
            execute.
        """
        engine = session.get_bind().name
        filters = cls._list_query_filters(engine, list_query)
        order_by = cls._list_query_order_by(engine, list_query)
        return await cls.list_paginated(
            session,
            *filters,
            order_by=order_by,
            pagination=pagination,
        )

    @classmethod
    async def list_service_types(cls, session: AsyncSession) -> tuple[list[str], bool]:
        """Return the distinct service types across the whole snippets table.

        Backs the list page's service-type filter so its options reflect the
        complete dataset rather than the loaded page. Blank and absent values are
        folded into the ``has_uncategorized`` flag rather than emitted as selectable
        values. The trimming shares :meth:`_service_type_exprs` with the list
        filter, so a value the facet omits as blank is the same one the filter
        treats as uncategorized.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :return: A tuple of the sorted distinct non-blank service types and whether
            any snippet has an absent or blank service type.
        :raises sqlalchemy.exc.SQLAlchemyError: When the query fails to execute.
        """
        engine = session.get_bind().name
        _, service_type_trimmed = cls._service_type_exprs(engine)
        values = (
            await cls._exec(session, select(service_type_trimmed).distinct())
        ).all()
        return sorted({value for value in values if value}), any(
            not value for value in values
        )

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        instance_create: Snippet,
        filter_include: set[str] | None = None,
        **extra_fields: Any,
    ) -> tuple[Snippet, bool]:
        """Retrieve an existing Snippet instance or create a new one if none exists.

        This method overrides the default `get_or_create` method to generate the `meta`
        field of the Snippet instance based on the snippet's path.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to filter and possibly create the
            instance.
        :type instance_create: Snippet
        :param filter_include: The set of fields of `instance_create` to be included in
            the search filter. Use None (default) for all fields.
        :param extra_fields: Additional fields to be set on the created instance.
        :type extra_fields: Any
        :return: The existing or newly created instance of `cls.Model`, and a bool
            specifying whether a new instance was created.
        :rtype: tuple[Snippet, bool]
        """
        existent_instance = await cls.first(
            session, **instance_create.model_dump(include=filter_include)
        )
        if existent_instance:
            return existent_instance, False
        await instance_create.update_meta()
        return await cls.create(session, instance_create, **extra_fields), True

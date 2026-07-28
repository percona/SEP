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
from app.core.db.list_query import ListQuerySpec
from app.core.pagination import PaginatedResponse, Pagination
from app.sep.snippets.list_query import SnippetApprovalFilter, SnippetListQuery
from app.sep.snippets.models import Snippet
from app.sep.snippets.models.meta import (
    META_KEY_DESCRIPTION,
    META_KEY_SERVICE_TYPE,
    META_KEY_TITLE,
)


def _meta_text(key: str) -> ColumnElement:
    """Return the ``meta`` JSON value at ``key`` as a text expression.

    One definition of "read this meta key" shared by the sort allowlist, the search
    set, the service-type filter, and the whole-dataset facet, so those four can
    never disagree on what a padded or absent value means. SQLAlchemy renders it per
    dialect (``->>`` on PostgreSQL, ``JSON_EXTRACT`` on SQLite), which also keeps it
    usable in a class-level spec where no session — and so no engine name — exists.

    :param key: The ``meta`` JSON key to read.
    :return: A text-typed column expression over ``Snippet.meta``.
    """
    return Snippet.meta[key].as_string()


class SnippetManager(BaseSQLModelManager):
    """Manage Snippet operations, including retrieval, listing, and deletion.

    :cvar Model: The SQLModel class this manager is responsible for (`Snippet`).
    :vartype Model: type[Snippet]
    :cvar ordering: The approved-first ordering (``approved_at`` desc, then
        ``created_at``). ``list_query_spec`` reproduces it as the spec default, so
        this attribute is redundant and a follow-up removes it; until then, callers
        that want the historical ordering byte-for-byte pass it as an explicit
        ``order_by``.
    :cvar list_query_spec: The request-boundary sort/search allowlist backing the
        derived list route, and the single authority for the default ordering.
        First-class columns sort and search directly; ``title`` and ``service_type``
        resolve through :func:`_meta_text`. The default sort reproduces the
        historical approved-first ordering, and the unique ``id`` tie-breaker keeps
        pagination deterministic.
    """

    Model = Snippet
    ordering = [col(Snippet.approved_at).desc(), "created_at"]
    list_query_spec = ListQuerySpec(
        sortable={
            "created_at": col(Snippet.created_at),
            "filename": col(Snippet.filename),
            "approved_at": col(Snippet.approved_at),
            "title": _meta_text(META_KEY_TITLE),
            "service_type": _meta_text(META_KEY_SERVICE_TYPE),
        },
        default_sort="-approved_at",
        tie_breaker=col(Snippet.id),
        searchable=(
            col(Snippet.filename),
            _meta_text(META_KEY_TITLE),
            _meta_text(META_KEY_DESCRIPTION),
        ),
    )

    @staticmethod
    def _service_type_exprs() -> tuple[ColumnElement, ColumnElement]:
        """Return the raw and trimmed ``meta.service_type`` expressions.

        The whole-dataset facet and the list filter normalise the free-form service
        type through this one definition, so a padded value groups identically on
        both paths instead of the facet and the predicate disagreeing on what counts
        as blank.

        :return: The raw meta-text expression and its ``TRIM``-normalised form.
        """
        raw = _meta_text(META_KEY_SERVICE_TYPE)
        return raw, func.trim(raw)

    @classmethod
    def _list_query_filters(
        cls, list_query: SnippetListQuery
    ) -> list[ColumnExpressionArgument[bool]]:
        """Build the filter predicates for a snippets list query.

        Sort and search are Core's, resolved into ``list_query.core``; what is built
        here is the snippets-specific approval and service-type restriction. They stay
        separate predicates so the applier folds them into the one clause set feeding
        both the count and the data query.

        :param list_query: The validated list-query selections.
        :return: The list of predicates (empty when nothing is filtered).
        """
        filters: list[ColumnExpressionArgument[bool]] = []

        if list_query.approval is SnippetApprovalFilter.APPROVED:
            filters.append(col(Snippet.approved_at).is_not(None))
        elif list_query.approval is SnippetApprovalFilter.NOT_APPROVED:
            filters.append(col(Snippet.approved_at).is_(None))

        service_type_raw, service_type_trimmed = cls._service_type_exprs()
        if list_query.uncategorized:
            filters.append(or_(service_type_raw.is_(None), service_type_trimmed == ""))
        elif list_query.service_type is not None:
            # Strip only spaces on the filter value to mirror SQL ``TRIM``'s default,
            # so the comparison agrees with the facet for tab/newline-padded values.
            filters.append(service_type_trimmed == list_query.service_type.strip(" "))

        return filters

    @classmethod
    async def snippet_list_page(
        cls,
        session: AsyncSession,
        *,
        list_query: SnippetListQuery,
        pagination: Pagination,
    ) -> PaginatedResponse[Snippet]:
        """Return a page of snippets with server-side search, filters, and sorting.

        The snippets filters compose with the Core-resolved sort and search in one
        whereclause set, so the paginated ``total`` matches the visible, filtered
        result set and the ordering carries the spec's unique tie-breaker.

        :param session: The SQLAlchemy asynchronous session to use for query execution.
        :param list_query: The validated sort/search/filter selections.
        :param pagination: The validated offset/limit window for this page.
        :return: A paginated response over the filtered, ordered snippets.
        :raises sqlalchemy.exc.SQLAlchemyError: When a count or data query fails to
            execute.
        """
        return await cls.list_query_paginated(
            session,
            *cls._list_query_filters(list_query),
            list_query=list_query.core,
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
        _, service_type_trimmed = cls._service_type_exprs()
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

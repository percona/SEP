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

"""Apply a :class:`~app.core.db.list_query.ListQuerySpec` to materialized rows.

A SQL-backed source pushes sort/search/pagination down to the database via
:meth:`~app.core.db.crud.BaseManager.list_query_paginated`. A source that has no
table — the disk-backed script source materializes its whole set from files —
cannot push down, so this module replays the same spec against in-process objects.

The spec is reused verbatim as a *declaration-only* value object, so an in-memory
source and a SQL source describe their orderable/searchable surface once, in one
type. The applier keys on **object attributes**, not SQL columns, resolving each
attribute name from the spec's column expressions: an in-memory spec must therefore
use named column clauses (``sqlalchemy.column("filename")``) whose name matches the
attribute exposed on the materialized row (for example ``_DiskScript.filename``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeVar

from fastapi import Query

from app.core.db.list_query import UnknownSortKeyError
from app.core.exceptions import HTTPUnprocessableEntityException

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from sqlalchemy.sql import ColumnExpressionArgument

    from app.core.db.list_query import ListQuerySpec
    from app.core.pagination import Pagination

S = TypeVar("S")


@dataclass(frozen=True, slots=True)
class InMemoryListQuery:
    """Carry a request's resolved, allowlist-vetted in-memory list-query selections.

    Holds the resolved public sort key (never a raw client column name), the
    direction, and the raw search term. The applier maps the sort key to an object
    attribute through the spec, so no client string reaches attribute access
    unvetted.

    :param sort_key: The vetted public sort key, with any ``-`` prefix stripped.
    :param descending: Whether the sort is descending (the ``-`` prefix was present).
    :param search: The raw search term, or ``None`` when search is disabled or unset.
    """

    sort_key: str
    descending: bool
    search: str | None


def _attr_name(column: ColumnExpressionArgument) -> str:
    """Return the object attribute a spec column expression names.

    :param column: A named column clause from the spec (``sortable`` value,
        ``tie_breaker``, or a ``searchable`` entry).
    :return: The attribute name to read off a materialized row.
    """
    return getattr(column, "name", None) or getattr(column, "key", "")


def make_in_memory_list_query_dep(
    spec: ListQuerySpec,
) -> Callable[..., InMemoryListQuery]:
    """Create a FastAPI dependency yielding a validated :class:`InMemoryListQuery`.

    Mirrors :func:`app.core.db.list_query.make_list_query_dep` exactly — two
    statically-defined inner functions so OpenAPI reflects the params, ``sort``
    always and ``search`` only when the spec's searchable set is non-empty, and an
    out-of-allowlist sort key rejected with HTTP 422 — so the in-memory and SQL list
    routes share one request-boundary contract.

    :param spec: The spec whose allowlist and searchable set bound the request.
    :return: A dependency callable resolving the request into an
        :class:`InMemoryListQuery`.
    """
    if spec.search_enabled:

        def _in_memory_list_query_dep(
            sort: str = Query(default=spec.default_sort),
            search: str | None = Query(default=None),
        ) -> InMemoryListQuery:
            return _build_in_memory_query(spec, sort, search)

        return _in_memory_list_query_dep

    def _in_memory_list_query_dep_no_search(
        sort: str = Query(default=spec.default_sort),
    ) -> InMemoryListQuery:
        return _build_in_memory_query(spec, sort, None)

    return _in_memory_list_query_dep_no_search


def _build_in_memory_query(
    spec: ListQuerySpec,
    sort: str,
    search: str | None,
) -> InMemoryListQuery:
    """Resolve a request's sort and search into an :class:`InMemoryListQuery`.

    Validation delegates to :meth:`ListQuerySpec.resolve_sort` so the allowlist and
    the 422 boundary are identical to the SQL dependency.

    :param spec: The spec whose allowlist bounds the request.
    :param sort: The requested public sort key (possibly ``-`` prefixed).
    :param search: The raw search term, or ``None`` when search is disabled or unset.
    :return: The resolved in-memory list query.
    :raises HTTPUnprocessableEntityException: When ``sort`` is not in the allowlist.
    """
    try:
        spec.resolve_sort(sort)
    except UnknownSortKeyError as exc:
        raise HTTPUnprocessableEntityException(
            detail=f"Invalid sort key: {exc.key!r}"
        ) from exc
    descending = sort.startswith("-")
    return InMemoryListQuery(
        sort_key=sort.removeprefix("-"),
        descending=descending,
        search=search,
    )


def apply_in_memory(
    items: Sequence[S],
    spec: ListQuerySpec,
    query: InMemoryListQuery,
    pagination: Pagination,
) -> tuple[list[S], int]:
    """Filter, order, and page ``items`` per the spec and resolved query.

    Replays the SQL path against in-process objects: case-insensitive substring
    search over the searchable attributes, then a NULLS-LAST, tie-broken ordering,
    then the pagination slice. The returned total is the filtered count taken before
    slicing, so it matches the SQL path's filtered total.

    :param items: The materialized rows to query.
    :param spec: The spec describing the searchable/sortable surface.
    :param query: The resolved, allowlist-vetted list-query selections.
    :param pagination: The offset/limit window for the page.
    :return: The page slice and the filtered total across all pages.
    """
    filtered = _search(items, spec, query.search)
    ordered = _sort(filtered, spec, query)
    return pagination.slice(ordered), len(ordered)


def _search(
    items: Sequence[S],
    spec: ListQuerySpec,
    search: str | None,
) -> list[S]:
    """Keep rows whose searchable attributes contain the term, case-insensitively.

    :param items: The rows to filter.
    :param spec: The spec whose searchable columns name the attributes to match.
    :param search: The raw search term; empty or whitespace-only keeps every row.
    :return: The rows matching the term (all rows when the term is blank).
    """
    term = search.strip().lower() if search else ""
    if not term:
        return list(items)
    attrs = [_attr_name(column) for column in spec.searchable]
    matched: list[S] = []
    for item in items:
        for attr in attrs:
            value = getattr(item, attr, None)
            if value is not None and term in str(value).lower():
                matched.append(item)
                break
    return matched


def _sort(
    items: Sequence[S],
    spec: ListQuerySpec,
    query: InMemoryListQuery,
) -> list[S]:
    """Order rows by the sort key NULLS-LAST, breaking ties on the tie-breaker.

    A stable ascending pre-pass on the tie-breaker fixes the order of equal-primary
    rows in both directions, matching ``ORDER BY <primary> <dir>, <tie-breaker> ASC``.
    Rows whose sort attribute is ``None`` are appended last regardless of direction,
    matching the SQL path's ``NULLS LAST``.

    :param items: The rows to order.
    :param spec: The spec whose sortable columns and tie-breaker name the attributes.
    :param query: The resolved sort key and direction.
    :return: The ordered rows.
    """
    sort_attr = _attr_name(spec.sortable[query.sort_key])
    tie_attr = _attr_name(spec.tie_breaker)
    rows = sorted(items, key=lambda item: getattr(item, tie_attr))
    present = [item for item in rows if getattr(item, sort_attr, None) is not None]
    absent = [item for item in rows if getattr(item, sort_attr, None) is None]
    present.sort(key=lambda item: getattr(item, sort_attr), reverse=query.descending)
    return present + absent


__all__ = [
    "InMemoryListQuery",
    "apply_in_memory",
    "make_in_memory_list_query_dep",
]

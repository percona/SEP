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

from app.core.db.list_query import (
    search_query_param,
    sort_query_param,
    UnknownSortKeyError,
)
from app.core.exceptions import HTTPUnprocessableEntityException

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable, Mapping, Sequence

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

    @classmethod
    def from_sort(cls, sort: str, search: str | None) -> InMemoryListQuery:
        """Split a ``-``-prefixed sort value into its key and direction.

        :param sort: A vetted sort value, descending when ``-`` prefixed.
        :param search: The raw search term, or ``None`` for no search.
        :return: The resolved selections.
        """
        return cls(
            sort_key=sort.removeprefix("-"),
            descending=sort.startswith("-"),
            search=search,
        )


def _attr_name(column: ColumnExpressionArgument, *, role: str) -> str:
    """Return the object attribute a spec column expression names.

    :param column: A named column clause from the spec (``sortable`` value,
        ``tie_breaker``, or a ``searchable`` entry).
    :param role: Where the column came from, for the error message.
    :return: The attribute name to read off a materialized row.
    :raises ValueError: When the expression carries neither a name nor a key, which
        would otherwise degrade into reading the empty attribute off every row.
    """
    name = getattr(column, "name", None) or getattr(column, "key", None)
    if not name:
        raise ValueError(
            f"in-memory list query: spec {role} expression {column!r} exposes no name "
            "or key to read off a row; use a named clause such as column('filename')"
        )
    return name


@dataclass(frozen=True, slots=True)
class _SpecAttrs:
    """Carry the row attribute names a spec's column expressions resolve to.

    :param sort_attrs: The attribute behind each public sort key.
    :param tie_attr: The attribute behind the tie-breaker.
    :param search_attrs: The attributes behind the searchable set.
    """

    sort_attrs: Mapping[str, str]
    tie_attr: str
    search_attrs: tuple[str, ...]


def _spec_attrs(spec: ListQuerySpec) -> _SpecAttrs:
    """Resolve every spec column expression to a row attribute name.

    :param spec: The spec to resolve.
    :return: The resolved attribute names.
    :raises ValueError: When any expression exposes no name or key.
    """
    return _SpecAttrs(
        sort_attrs={
            key: _attr_name(column, role=f"sortable[{key!r}]")
            for key, column in spec.sortable.items()
        },
        tie_attr=_attr_name(spec.tie_breaker, role="tie_breaker"),
        search_attrs=tuple(
            _attr_name(column, role="searchable") for column in spec.searchable
        ),
    )


def _require_row_attrs(row: object, attrs: Iterable[tuple[str, str]]) -> None:
    """Reject a row that does not expose every attribute the spec will read.

    Sampled once per call against the first row rather than per row: the applier's
    inputs are homogeneous sequences, so one row settles it, and a spec/row mismatch
    is a wiring error that should name both sides instead of surfacing as a bare
    ``AttributeError`` from inside a sort key.

    :param row: A representative materialized row.
    :param attrs: ``(role, attribute)`` pairs the applier will read.
    :raises ValueError: When the row lacks one of the attributes.
    """
    for role, attr in attrs:
        if not hasattr(row, attr):
            raise ValueError(
                f"in-memory list query: {type(row).__name__} has no attribute "
                f"{attr!r} named by spec {role}"
            )


def make_in_memory_list_query_dep(
    spec: ListQuerySpec,
) -> Callable[..., InMemoryListQuery]:
    """Create a FastAPI dependency yielding a validated :class:`InMemoryListQuery`.

    Presents the same request boundary as
    :func:`app.core.db.list_query.make_list_query_dep`: ``sort`` always, ``search``
    only when the spec's searchable set is non-empty, and an out-of-allowlist sort key
    rejected with HTTP 422. The allowlist check, the error type, and the 422 mapping are
    Core's, reached through :meth:`ListQuerySpec.resolve_sort` and
    :class:`UnknownSortKeyError`. The parameter declarations themselves are Core's too,
    through :func:`~app.core.db.list_query.sort_query_param` and
    :func:`~app.core.db.list_query.search_query_param`, so the description and the
    allowlist ``enum`` a generated client reads are identical on both paths. What
    remains restated is the two-statically-defined-inner-functions shape FastAPI needs
    to reflect the params into OpenAPI.

    :param spec: The spec whose allowlist and searchable set bound the request.
    :return: A dependency callable resolving the request into an
        :class:`InMemoryListQuery`.
    :raises ValueError: When a spec column expression exposes no name to read off a
        row, so a misdeclared spec fails at wiring time rather than per request.
    """
    # Resolved for its exception only: a misdeclared spec has to fail here, at wiring
    # time, rather than once per request inside the applier.
    _spec_attrs(spec)
    if spec.search_enabled:

        def _in_memory_list_query_dep(
            sort: str = sort_query_param(spec),
            search: str | None = search_query_param(),
        ) -> InMemoryListQuery:
            return build_in_memory_list_query(spec, sort, search)

        return _in_memory_list_query_dep

    def _in_memory_list_query_dep_no_search(
        sort: str = sort_query_param(spec),
    ) -> InMemoryListQuery:
        return build_in_memory_list_query(spec, sort, None)

    return _in_memory_list_query_dep_no_search


def build_in_memory_list_query(
    spec: ListQuerySpec,
    sort: str,
    search: str | None,
) -> InMemoryListQuery:
    """Resolve a request's sort and search into an :class:`InMemoryListQuery`.

    Validation delegates to :meth:`ListQuerySpec.resolve_sort` so the allowlist and
    the 422 boundary are identical to the SQL dependency. Public so a hand-written
    route — for example a proxied inventory list that dispatches across per-entity
    specs — can reuse the same mapping without going through
    :func:`make_in_memory_list_query_dep`.

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
    return InMemoryListQuery.from_sort(sort, search)


def default_in_memory_query(spec: ListQuerySpec) -> InMemoryListQuery:
    """Return the query a request that selected nothing resolves to.

    Lets a caller with no request-derived query — the whole-collection call shape — run
    the same applier as a queried one, so a source needs no second, order-less path.

    :param spec: The spec whose default sort to adopt.
    :return: The spec's default sort with no search term.
    """
    return InMemoryListQuery.from_sort(spec.default_sort, None)


def apply_in_memory(
    items: Sequence[S],
    spec: ListQuerySpec,
    query: InMemoryListQuery,
    pagination: Pagination | None,
) -> tuple[list[S], int]:
    """Filter, order, and page ``items`` per the spec and resolved query.

    Replays the SQL path against in-process objects: case-insensitive substring
    search over the searchable attributes, then a NULLS-LAST, tie-broken ordering,
    then the pagination slice. The returned total is the filtered count taken before
    slicing, so it matches the SQL path's filtered total.

    :param items: The materialized rows to query.
    :param spec: The spec describing the searchable/sortable surface.
    :param query: The resolved, allowlist-vetted list-query selections.
    :param pagination: The offset/limit window for the page, or ``None`` to return
        every matching row unsliced (the whole-collection call shape).
    :return: The page slice and the filtered total across all pages.
    :raises ValueError: When a spec column expression exposes no name, or the rows do
        not expose an attribute the spec names.
    :raises UnknownSortKeyError: When ``query.sort_key`` is outside the allowlist.
    """
    attrs = _spec_attrs(spec)
    if query.sort_key not in attrs.sort_attrs:
        raise UnknownSortKeyError(query.sort_key)
    if items:
        _require_row_attrs(
            items[0],
            [
                (f"sortable[{query.sort_key!r}]", attrs.sort_attrs[query.sort_key]),
                ("tie_breaker", attrs.tie_attr),
                *(("searchable", attr) for attr in attrs.search_attrs),
            ],
        )
    filtered = _search(items, attrs, query.search)
    ordered = _sort(filtered, attrs, query)
    return (ordered if pagination is None else pagination.slice(ordered)), len(ordered)


def in_memory_list_scripts(
    materialize: Callable[[], Awaitable[Sequence[S]]],
    spec: ListQuerySpec,
) -> Callable[
    [InMemoryListQuery | None, Pagination | None], Awaitable[tuple[list[S], int]]
]:
    """Adapt a materialize-everything callable into the widened list-scripts contract.

    A source that fetches its whole set has one honest implementation of all four call
    shapes — query or not, paginated or not — so it is written once here rather than as
    a branch cascade per source. A missing query resolves to the spec default, which is
    what removes the need for an unsorted, unfiltered fallback path.

    Nothing here assumes a script type: any homogeneous sequence of rows exposing the
    spec's attributes works, so a hand-written route outside the script seam can use it.

    :param materialize: Fetches the complete set of rows.
    :param spec: The spec bounding the sort, search, and default ordering.
    :return: A callable honouring the ``ScriptSource.list_scripts`` contract.
    """

    async def list_scripts(
        list_query: InMemoryListQuery | None, pagination: Pagination | None
    ) -> tuple[list[S], int]:
        return apply_in_memory(
            await materialize(),
            spec,
            list_query or default_in_memory_query(spec),
            pagination,
        )

    return list_scripts


def _search(
    items: Sequence[S],
    attrs: _SpecAttrs,
    search: str | None,
) -> list[S]:
    """Keep rows whose searchable attributes contain the term, case-insensitively.

    :param items: The rows to filter.
    :param attrs: The resolved attribute names to match against.
    :param search: The raw search term; empty or whitespace-only keeps every row.
    :return: The rows matching the term (all rows when the term is blank).
    """
    term = search.strip().lower() if search else ""
    if not term:
        return list(items)

    def matches(item: S) -> bool:
        return any(
            term in str(value).lower()
            for attr in attrs.search_attrs
            if (value := getattr(item, attr)) is not None
        )

    return [item for item in items if matches(item)]


def _sort(
    items: Sequence[S],
    attrs: _SpecAttrs,
    query: InMemoryListQuery,
) -> list[S]:
    """Order rows by the sort key NULLS-LAST, breaking ties on the tie-breaker.

    A stable ascending pre-pass on the tie-breaker fixes the order of equal-primary
    rows in both directions, matching ``ORDER BY <primary> <dir>, <tie-breaker> ASC``.
    Rows whose sort attribute is ``None`` are appended last regardless of direction,
    matching the SQL path's ``NULLS LAST``.

    :param items: The rows to order.
    :param attrs: The resolved sortable and tie-breaker attribute names.
    :param query: The resolved sort key and direction.
    :return: The ordered rows.
    """
    sort_attr = attrs.sort_attrs[query.sort_key]
    rows = sorted(items, key=lambda item: getattr(item, attrs.tie_attr))
    present: list[S] = []
    absent: list[S] = []
    for item in rows:
        (absent if getattr(item, sort_attr) is None else present).append(item)
    present.sort(key=lambda item: getattr(item, sort_attr), reverse=query.descending)
    return present + absent


__all__ = [
    "InMemoryListQuery",
    "apply_in_memory",
    "build_in_memory_list_query",
    "default_in_memory_query",
    "in_memory_list_scripts",
    "make_in_memory_list_query_dep",
]

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

"""Test the framework's in-memory list-query applier and its request dependency."""

from __future__ import annotations

import inspect
from dataclasses import dataclass

import pytest
from pydantic import BaseModel
from sqlalchemy import column

from app.core.db.list_query import ListQuerySpec
from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.pagination import Pagination
from app.sep.apps.framework import list_query as list_query_module
from app.sep.apps.framework.list_query import (
    apply_in_memory,
    InMemoryListQuery,
    make_in_memory_list_query_dep,
)


@dataclass(frozen=True, slots=True)
class _Row:
    """Stand in for a materialized in-memory script row."""

    filename: str
    title: str | None
    created_at: int


SPEC = ListQuerySpec(
    sortable={
        "filename": column("filename"),
        "title": column("title"),
        "created_at": column("created_at"),
    },
    default_sort="-created_at",
    tie_breaker=column("filename"),
    searchable=(column("filename"), column("title")),
)

NO_SEARCH_SPEC = ListQuerySpec(
    sortable={"filename": column("filename")},
    default_sort="filename",
    tie_breaker=column("filename"),
)


def _rows(*specs: tuple[str, str | None, int]) -> list[_Row]:
    return [_Row(filename=f, title=t, created_at=c) for f, t, c in specs]


class TestMakeInMemoryListQueryDep:
    """Exercise the FastAPI dependency the paginated list route injects."""

    def test_exposes_sort_and_search_params_when_searchable(self) -> None:
        """Expose ``sort`` and ``search`` when the spec has searchable columns."""
        dep = make_in_memory_list_query_dep(SPEC)
        params = inspect.signature(dep).parameters
        assert set(params) == {"sort", "search"}

    def test_exposes_only_sort_when_no_searchable(self) -> None:
        """Expose only ``sort`` when the spec has no searchable columns."""
        dep = make_in_memory_list_query_dep(NO_SEARCH_SPEC)
        params = inspect.signature(dep).parameters
        assert set(params) == {"sort"}

    def test_default_sort_resolves_to_spec_default(self) -> None:
        """Resolve the spec's default sort, honoring its descending prefix."""
        dep = make_in_memory_list_query_dep(SPEC)
        query = dep(sort=SPEC.default_sort, search=None)
        assert query == InMemoryListQuery(
            sort_key="created_at", descending=True, search=None
        )

    def test_ascending_sort_key_parsed(self) -> None:
        """Parse a bare (unprefixed) sort key as ascending."""
        dep = make_in_memory_list_query_dep(SPEC)
        assert dep(sort="filename", search=None).descending is False

    def test_search_term_passed_through(self) -> None:
        """Carry the raw search term onto the resolved query."""
        dep = make_in_memory_list_query_dep(SPEC)
        assert dep(sort="filename", search="needle").search == "needle"

    def test_unknown_sort_key_raises_422(self) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422."""
        dep = make_in_memory_list_query_dep(SPEC)
        with pytest.raises(HTTPUnprocessableEntityException):
            dep(sort="bogus", search=None)

    def test_unknown_sort_key_with_descending_prefix_raises_422(self) -> None:
        """Reject an out-of-allowlist descending sort key with HTTP 422."""
        dep = make_in_memory_list_query_dep(SPEC)
        with pytest.raises(HTTPUnprocessableEntityException):
            dep(sort="-bogus", search=None)


class TestApplyInMemorySort:
    """Verify ordering matches the SQL path: direction, NULLS-LAST, tie-breaker."""

    def test_descending_primary(self) -> None:
        """Order rows by the primary key descending."""
        rows = _rows(("a", "A", 1), ("b", "B", 3), ("c", "C", 2))
        query = InMemoryListQuery(sort_key="created_at", descending=True, search=None)
        page, total = apply_in_memory(rows, SPEC, query, Pagination())
        assert [r.filename for r in page] == ["b", "c", "a"]
        assert total == len(rows)

    def test_ascending_primary(self) -> None:
        """Order rows by the primary key ascending."""
        rows = _rows(("a", "A", 1), ("b", "B", 3), ("c", "C", 2))
        query = InMemoryListQuery(sort_key="created_at", descending=False, search=None)
        page, _ = apply_in_memory(rows, SPEC, query, Pagination())
        assert [r.filename for r in page] == ["a", "c", "b"]

    def test_nulls_sort_last_regardless_of_direction(self) -> None:
        """Trail NULL sort values last in both ascending and descending order."""
        rows = _rows(("a", None, 1), ("b", "B", 2), ("c", None, 3))
        asc = InMemoryListQuery(sort_key="title", descending=False, search=None)
        desc = InMemoryListQuery(sort_key="title", descending=True, search=None)
        asc_page, _ = apply_in_memory(rows, SPEC, asc, Pagination())
        desc_page, _ = apply_in_memory(rows, SPEC, desc, Pagination())
        # Non-null "B" leads both directions; NULL rows trail, ordered by tie-breaker.
        assert [r.filename for r in asc_page] == ["b", "a", "c"]
        assert [r.filename for r in desc_page] == ["b", "a", "c"]

    def test_tie_breaker_makes_equal_primary_deterministic(self) -> None:
        """Break equal-primary ties on the tie-breaker ascending, both directions."""
        rows = _rows(("c", "X", 5), ("a", "X", 5), ("b", "X", 5))
        asc = InMemoryListQuery(sort_key="created_at", descending=False, search=None)
        desc = InMemoryListQuery(sort_key="created_at", descending=True, search=None)
        asc_page, _ = apply_in_memory(rows, SPEC, asc, Pagination())
        desc_page, _ = apply_in_memory(rows, SPEC, desc, Pagination())
        # Equal primary → filename tie-breaker ascending in BOTH directions.
        assert [r.filename for r in asc_page] == ["a", "b", "c"]
        assert [r.filename for r in desc_page] == ["a", "b", "c"]


class TestApplyInMemorySearch:
    """Verify case-insensitive substring search and the filtered total."""

    def test_case_insensitive_substring_over_searchable_attrs(self) -> None:
        """Match a term case-insensitively as a substring of a searchable attr."""
        rows = _rows(("alpha.sh", "First", 1), ("beta.sh", "Second", 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="FIR")
        page, total = apply_in_memory(rows, SPEC, query, Pagination())
        assert [r.filename for r in page] == ["alpha.sh"]
        assert total == 1

    def test_search_matches_filename_column(self) -> None:
        """Match the term against the filename attribute."""
        rows = _rows(("alpha.sh", None, 1), ("beta.sh", None, 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="beta")
        page, total = apply_in_memory(rows, SPEC, query, Pagination())
        assert [r.filename for r in page] == ["beta.sh"]
        assert total == 1

    def test_none_searchable_value_skipped(self) -> None:
        """Skip a row whose only match candidate is a ``None`` attribute."""
        rows = _rows(("alpha.sh", None, 1))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="x")
        page, total = apply_in_memory(rows, SPEC, query, Pagination())
        assert page == []
        assert total == 0

    def test_whitespace_only_search_ignored(self) -> None:
        """Treat a whitespace-only term as no search."""
        rows = _rows(("a", "A", 1), ("b", "B", 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="   ")
        _, total = apply_in_memory(rows, SPEC, query, Pagination())
        assert total == len(rows)

    def test_none_search_returns_all(self) -> None:
        """Return every row when no search term is supplied."""
        rows = _rows(("a", "A", 1), ("b", "B", 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)
        _, total = apply_in_memory(rows, SPEC, query, Pagination())
        assert total == len(rows)


class TestApplyInMemoryPagination:
    """Verify slicing and that the total reflects the filtered set, not the page."""

    def test_total_is_filtered_count_before_slice(self) -> None:
        """Report the filtered total across all pages, not the sliced page size."""
        row_count, page_limit = 10, 3
        rows = _rows(*[(f"{i:02d}.sh", "T", i) for i in range(row_count)])
        query = InMemoryListQuery(sort_key="filename", descending=False, search="T")
        page, total = apply_in_memory(
            rows, SPEC, query, Pagination(offset=0, limit=page_limit)
        )
        assert len(page) == page_limit
        assert total == row_count

    def test_offset_and_limit_window(self) -> None:
        """Return exactly the offset/limit window of the ordered set."""
        rows = _rows(*[(f"{i:02d}.sh", None, i) for i in range(5)])
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)
        page, _ = apply_in_memory(rows, SPEC, query, Pagination(offset=2, limit=2))
        assert [r.filename for r in page] == ["02.sh", "03.sh"]

    def test_empty_items(self) -> None:
        """Return an empty page and zero total for an empty input."""
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)
        page, total = apply_in_memory([], SPEC, query, Pagination())
        assert page == []
        assert total == 0


class TestApplierIsBackingAgnostic:
    """Pin the applier's independence from the script seam.

    A hand-written route outside the script framework (the proxied inventory list is
    the next consumer) takes the dependency and applies the result over whatever rows
    it materialized, so the applier must not assume a script type — or drag the script
    seam in as an import.
    """

    def test_applies_over_pydantic_rows(self) -> None:
        """Sort, search, and total plain Pydantic rows, not just script dataclasses."""

        class _Node(BaseModel):
            filename: str
            title: str | None = None
            created_at: int = 0

        matching = 2
        rows = [
            _Node(filename="b-node", title="Beta"),
            _Node(filename="a-node", title="Alpha"),
            _Node(filename="c-node", title="Gamma alpha"),
        ]
        query = InMemoryListQuery(sort_key="filename", descending=False, search="alpha")

        page, total = apply_in_memory(rows, SPEC, query, Pagination())

        assert [row.filename for row in page] == ["a-node", "c-node"]
        assert total == matching

    def test_module_does_not_import_the_script_seam(self) -> None:
        """Keep the applier importable without pulling in ``ScriptSource``."""
        source = inspect.getsource(list_query_module)
        assert "script_source" not in source
        assert "ScriptSource" not in source

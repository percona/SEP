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

"""Test the framework's spec-bound in-memory list-query applier."""

from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING

import pytest
from pydantic import BaseModel
from sqlalchemy import cast, column, String

from app.core.db.list_query import (
    ListQuerySpec,
    UnknownSortKeyError,
)
from app.core.pagination import Pagination
from app.sep.apps.framework import list_query as list_query_module
from app.sep.apps.framework.list_query import (
    InMemoryListQuery,
    InMemoryListQueryApplier,
)
from tests.app.sep.apps.framework.list_query_kit import (
    make_rows,
    NO_SEARCH_SPEC,
    Row,
    SPEC,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import TypeAlias


APPLIER = InMemoryListQueryApplier(SPEC)
NO_SEARCH_APPLIER = InMemoryListQueryApplier(NO_SEARCH_SPEC)


if TYPE_CHECKING:
    ListScripts: TypeAlias = Callable[
        [InMemoryListQuery | None, Pagination | None],
        Awaitable[tuple[list[Row], int]],
    ]


def _forbid_spec_attrs(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail the test if the spec attribute mapping is resolved again.

    :param monkeypatch: The fixture patching the applier module.
    """

    def _boom(spec: ListQuerySpec) -> None:
        raise AssertionError(f"spec attributes re-resolved for {spec!r}")

    monkeypatch.setattr(list_query_module, "_spec_attrs", _boom)


class TestApplierConstruction:
    """Pin that the spec binds — and is validated — once, at construction."""

    def test_binds_the_spec_and_its_resolved_attributes(self) -> None:
        """Hold the spec and the row attributes its expressions name."""
        applier = InMemoryListQueryApplier(SPEC)

        assert applier.spec is SPEC
        assert applier._attrs.sort_attrs == {
            "filename": "filename",
            "title": "title",
            "created_at": "created_at",
        }
        assert applier._attrs.tie_attr == "filename"
        assert applier._attrs.search_attrs == ("filename", "title")

    def test_resolved_mapping_cannot_be_mutated(self) -> None:
        """Reject an in-place edit of the resolved sort mapping.

        The applier is reached from module scope by every request, so a writable
        mapping would let one caller repoint another's sort key at a different
        attribute for the process's lifetime.
        """
        applier = InMemoryListQueryApplier(SPEC)

        with pytest.raises(TypeError):
            applier._attrs.sort_attrs["filename"] = "created_at"  # type: ignore[index]

        assert applier._attrs.sort_attrs["filename"] == "filename"

    def test_attributes_are_never_resolved_again(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serve every per-call operation from the construction-time mapping.

        The whole point of binding the spec: a request must not re-walk the spec's
        column expressions, so re-resolution is made fatal for the duration.
        """
        applier = InMemoryListQueryApplier(SPEC)
        rows = make_rows(("b.sh", "Beta", 2), ("a.sh", "Alpha", 1))
        _forbid_spec_attrs(monkeypatch)

        for _ in range(2):
            applier.apply(rows, applier.default_query(), Pagination())
        applier.apply(rows, applier.build_query("filename", "alpha"), None)

    def test_unnamed_sortable_column_rejected(self) -> None:
        """Reject an unnamed sort expression when the applier is built."""
        spec = ListQuerySpec(
            sortable={"size": cast(column("size"), String)},
            default_sort="size",
            tie_breaker=column("filename"),
        )

        with pytest.raises(ValueError, match="exposes no name"):
            InMemoryListQueryApplier(spec)

    @pytest.mark.parametrize("role", ["tie_breaker", "searchable"])
    def test_unnamed_non_sortable_expression_also_rejected(self, role: str) -> None:
        """Guard every role at construction, not just the sortable allowlist."""
        unnamed = cast(column("filename"), String)
        spec = ListQuerySpec(
            sortable={"filename": column("filename")},
            default_sort="filename",
            tie_breaker=unnamed if role == "tie_breaker" else column("filename"),
            searchable=[unnamed] if role == "searchable" else [],
        )

        with pytest.raises(ValueError, match=f"spec {role}"):
            InMemoryListQueryApplier(spec)

    def test_no_applier_escapes_a_misdeclared_spec(self) -> None:
        """Leave no half-built applier behind: construction is the only way in.

        The applier is the sole entry point to the in-memory path, so a spec whose
        tie-breaker cannot be read off a row cannot reach a request at all.
        """
        spec = ListQuerySpec(
            sortable={"filename": column("filename")},
            default_sort="filename",
            tie_breaker=cast(column("filename"), String),
        )

        with pytest.raises(ValueError, match="tie_breaker"):
            InMemoryListQueryApplier(spec).apply(
                make_rows(("a.sh", None, 1)),
                InMemoryListQuery(sort_key="filename", descending=False, search=None),
                Pagination(),
            )


class TestBuildQuery:
    """Cover the public builder a hand-written route calls without a FastAPI dep."""

    def test_resolves_sort_and_search(self) -> None:
        """Carry a vetted sort key and search term onto the resolved query."""
        query = APPLIER.build_query("-filename", "needle")
        assert query == InMemoryListQuery(
            sort_key="filename", descending=True, search="needle"
        )

    def test_unknown_sort_key_raises_the_domain_error(self) -> None:
        """Reject an out-of-allowlist sort key as the domain error, not an HTTP one.

        The 422 belongs to the request boundary — Core's generated dependency, or a
        hand-written one — so the applier states the rejection once, in its own terms,
        and no caller is forced to catch an HTTP exception to resolve a query.
        """
        with pytest.raises(UnknownSortKeyError) as excinfo:
            APPLIER.build_query("bogus", None)
        assert excinfo.value.key == "bogus"


class TestApplySort:
    """Verify ordering matches the SQL path: direction, NULLS-LAST, tie-breaker."""

    def test_descending_primary(self) -> None:
        """Order rows by the primary key descending."""
        rows = make_rows(("a", "A", 1), ("b", "B", 3), ("c", "C", 2))
        query = InMemoryListQuery(sort_key="created_at", descending=True, search=None)
        page, total = APPLIER.apply(rows, query, Pagination())
        assert [r.filename for r in page] == ["b", "c", "a"]
        assert total == len(rows)

    def test_ascending_primary(self) -> None:
        """Order rows by the primary key ascending."""
        rows = make_rows(("a", "A", 1), ("b", "B", 3), ("c", "C", 2))
        query = InMemoryListQuery(sort_key="created_at", descending=False, search=None)
        page, _ = APPLIER.apply(rows, query, Pagination())
        assert [r.filename for r in page] == ["a", "c", "b"]

    def test_nulls_sort_last_regardless_of_direction(self) -> None:
        """Trail NULL sort values last in both ascending and descending order."""
        rows = make_rows(("a", None, 1), ("b", "B", 2), ("c", None, 3))
        asc = InMemoryListQuery(sort_key="title", descending=False, search=None)
        desc = InMemoryListQuery(sort_key="title", descending=True, search=None)
        asc_page, _ = APPLIER.apply(rows, asc, Pagination())
        desc_page, _ = APPLIER.apply(rows, desc, Pagination())
        # Non-null "B" leads both directions; NULL rows trail, ordered by tie-breaker.
        assert [r.filename for r in asc_page] == ["b", "a", "c"]
        assert [r.filename for r in desc_page] == ["b", "a", "c"]

    def test_tie_breaker_makes_equal_primary_deterministic(self) -> None:
        """Break equal-primary ties on the tie-breaker ascending, both directions."""
        rows = make_rows(("c", "X", 5), ("a", "X", 5), ("b", "X", 5))
        asc = InMemoryListQuery(sort_key="created_at", descending=False, search=None)
        desc = InMemoryListQuery(sort_key="created_at", descending=True, search=None)
        asc_page, _ = APPLIER.apply(rows, asc, Pagination())
        desc_page, _ = APPLIER.apply(rows, desc, Pagination())
        # Equal primary → filename tie-breaker ascending in BOTH directions.
        assert [r.filename for r in asc_page] == ["a", "b", "c"]
        assert [r.filename for r in desc_page] == ["a", "b", "c"]


class TestApplySearch:
    """Verify case-insensitive substring search and the filtered total."""

    def test_case_insensitive_substring_over_searchable_attrs(self) -> None:
        """Match a term case-insensitively as a substring of a searchable attr."""
        rows = make_rows(("alpha.sh", "First", 1), ("beta.sh", "Second", 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="FIR")
        page, total = APPLIER.apply(rows, query, Pagination())
        assert [r.filename for r in page] == ["alpha.sh"]
        assert total == 1

    def test_search_matches_filename_column(self) -> None:
        """Match the term against the filename attribute."""
        rows = make_rows(("alpha.sh", None, 1), ("beta.sh", None, 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="beta")
        page, total = APPLIER.apply(rows, query, Pagination())
        assert [r.filename for r in page] == ["beta.sh"]
        assert total == 1

    def test_none_searchable_value_skipped(self) -> None:
        """Skip a row whose only match candidate is a ``None`` attribute."""
        rows = make_rows(("alpha.sh", None, 1))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="x")
        page, total = APPLIER.apply(rows, query, Pagination())
        assert page == []
        assert total == 0

    def test_whitespace_only_search_ignored(self) -> None:
        """Treat a whitespace-only term as no search."""
        rows = make_rows(("a", "A", 1), ("b", "B", 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="   ")
        _, total = APPLIER.apply(rows, query, Pagination())
        assert total == len(rows)

    def test_none_search_returns_all(self) -> None:
        """Return every row when no search term is supplied."""
        rows = make_rows(("a", "A", 1), ("b", "B", 2))
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)
        _, total = APPLIER.apply(rows, query, Pagination())
        assert total == len(rows)

    def test_non_string_searchable_value_matched_as_text(self) -> None:
        """Match a non-string searchable attribute through its text form.

        A spec is free to make a numeric attribute searchable; SQL ``ilike`` casts it,
        so the in-memory path has to compare the same way rather than skipping it.
        """
        applier = InMemoryListQueryApplier(
            ListQuerySpec(
                sortable={"filename": column("filename")},
                default_sort="filename",
                tie_breaker=column("filename"),
                searchable=(column("created_at"),),
            )
        )
        rows = make_rows(("a", "A", 17), ("b", "B", 42))
        query = InMemoryListQuery(sort_key="filename", descending=False, search="17")

        page, total = applier.apply(rows, query, Pagination())

        assert [row.filename for row in page] == ["a"]
        assert total == 1


class TestApplyPagination:
    """Verify slicing and that the total reflects the filtered set, not the page."""

    def test_total_is_filtered_count_before_slice(self) -> None:
        """Report the filtered total across all pages, not the sliced page size."""
        row_count, page_limit = 10, 3
        rows = make_rows(*[(f"{i:02d}.sh", "T", i) for i in range(row_count)])
        query = InMemoryListQuery(sort_key="filename", descending=False, search="T")
        page, total = APPLIER.apply(rows, query, Pagination(offset=0, limit=page_limit))
        assert len(page) == page_limit
        assert total == row_count

    def test_offset_and_limit_window(self) -> None:
        """Return exactly the offset/limit window of the ordered set."""
        rows = make_rows(*[(f"{i:02d}.sh", None, i) for i in range(5)])
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)
        page, _ = APPLIER.apply(rows, query, Pagination(offset=2, limit=2))
        assert [r.filename for r in page] == ["02.sh", "03.sh"]

    def test_empty_items(self) -> None:
        """Return an empty page and zero total for an empty input."""
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)
        page, total = APPLIER.apply([], query, Pagination())
        assert page == []
        assert total == 0


class TestDefaultQuery:
    """Cover the query a caller with no request-derived selections falls back to."""

    def test_descending_default_strips_the_prefix(self) -> None:
        """Split a ``-`` prefixed default into a bare key plus a descending flag."""
        query = APPLIER.default_query()

        assert (query.sort_key, query.descending, query.search) == (
            "created_at",
            True,
            None,
        )

    def test_ascending_default_is_not_descending(self) -> None:
        """Keep an unprefixed default ascending."""
        query = NO_SEARCH_APPLIER.default_query()

        assert (query.sort_key, query.descending) == ("filename", False)


class TestApplyWithoutPagination:
    """Cover the whole-collection call shape the derived non-paginated route makes."""

    def test_returns_every_row_unsliced(self) -> None:
        """Return the full ordered set, past a default page, when pagination is None."""
        row_count = 60
        rows = make_rows(*[(f"{i:02d}.sh", "T", i) for i in range(row_count)])
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)

        page, total = APPLIER.apply(rows, query, None)

        assert len(page) == row_count
        assert total == row_count
        assert page[0].filename == "00.sh"

    def test_still_filters_and_orders(self) -> None:
        """Apply search and ordering even with no page window."""
        rows = make_rows(
            ("b.sh", "Beta", 2), ("a.sh", "Alpha", 1), ("c.sh", "Gamma", 3)
        )
        query = InMemoryListQuery(sort_key="filename", descending=True, search="a")

        page, total = APPLIER.apply(rows, query, None)

        assert [row.filename for row in page] == ["c.sh", "b.sh", "a.sh"]
        assert total == len(rows)


class TestSpecAttributeValidation:
    """Pin that a spec/row mismatch fails loudly, and once, rather than per row."""

    def test_row_missing_spec_attribute_names_both_sides(self) -> None:
        """Name the row type and the attribute instead of raising ``AttributeError``."""

        class _Sparse(BaseModel):
            filename: str

        query = InMemoryListQuery(sort_key="created_at", descending=False, search=None)

        with pytest.raises(ValueError, match="_Sparse has no attribute 'created_at'"):
            APPLIER.apply([_Sparse(filename="a.sh")], query, Pagination())

    def test_out_of_allowlist_sort_key_rejected(self) -> None:
        """Reject a hand-built query whose sort key was never vetted by the spec."""
        query = InMemoryListQuery(sort_key="secret", descending=False, search=None)

        with pytest.raises(UnknownSortKeyError):
            APPLIER.apply(make_rows(("a.sh", None, 1)), query, Pagination())

    @pytest.mark.parametrize("sort_key", ["__class__", "__dict__"])
    def test_dunder_sort_key_rejected(self, sort_key: str) -> None:
        """Reject a dunder sort key, which the allowlist gate keeps out of ``getattr``.

        The ordering reads the sort key off each row as an attribute, so an unvetted key
        would otherwise sort on object internals rather than on data.
        """
        query = InMemoryListQuery(sort_key=sort_key, descending=False, search=None)

        with pytest.raises(UnknownSortKeyError):
            APPLIER.apply(make_rows(("a.sh", None, 1)), query, Pagination())

    def test_row_missing_searchable_attribute_names_both_sides(self) -> None:
        """Reject a searchable-only mismatch on the first list call, not the first search.

        The sortable and tie-breaker attributes can line up while a searchable one does
        not, and the search attributes are read only for a non-blank term — so checking
        them lazily would defer a wiring error to whichever request first searched.
        """

        class _Untitled(BaseModel):
            filename: str
            created_at: int = 0

        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)

        with pytest.raises(ValueError, match="_Untitled has no attribute 'title'"):
            APPLIER.apply([_Untitled(filename="a.sh")], query, Pagination())


_ADAPTER_ROWS = 3


class TestListScripts:
    """Cover the adapter across all four shapes the framework calls it with."""

    @pytest.fixture
    def list_scripts(self) -> ListScripts:
        """Adapt a fixed set of rows through the framework's applier.

        :return: The bound list-scripts callable over a fixed row set.
        """
        rows = make_rows(
            ("b.sh", "Beta", 2), ("a.sh", "Alpha", 1), ("c.sh", "Gamma", 3)
        )

        async def _materialize() -> list[Row]:
            return rows

        return APPLIER.list_scripts(_materialize)

    @pytest.mark.asyncio
    async def test_no_query_no_pagination_returns_all_in_spec_order(
        self, list_scripts: ListScripts
    ) -> None:
        """Order by the spec default and return everything for the bare call."""
        page, total = await list_scripts(None, None)

        assert [row.filename for row in page] == ["c.sh", "b.sh", "a.sh"]
        assert total == _ADAPTER_ROWS

    @pytest.mark.asyncio
    async def test_no_query_with_pagination_slices_in_spec_order(
        self, list_scripts: ListScripts
    ) -> None:
        """Slice the spec-default order rather than the materialization order."""
        page, total = await list_scripts(None, Pagination(offset=0, limit=2))

        assert [row.filename for row in page] == ["c.sh", "b.sh"]
        assert total == _ADAPTER_ROWS

    @pytest.mark.asyncio
    async def test_query_without_pagination_filters_unsliced(
        self, list_scripts: ListScripts
    ) -> None:
        """Honour a resolved query with no page window."""
        query = InMemoryListQuery(sort_key="filename", descending=False, search="alpha")

        page, total = await list_scripts(query, None)

        assert [row.filename for row in page] == ["a.sh"]
        assert total == 1

    @pytest.mark.asyncio
    async def test_query_with_pagination_filters_and_slices(
        self, list_scripts: ListScripts
    ) -> None:
        """Honour a resolved query and report the filtered total, not the page size."""
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)

        page, total = await list_scripts(query, Pagination(offset=1, limit=1))

        assert [row.filename for row in page] == ["b.sh"]
        assert total == _ADAPTER_ROWS

    @pytest.mark.asyncio
    async def test_adapter_resolves_no_spec_attributes_per_call(
        self, list_scripts: ListScripts, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Serve every list call from the applier the source was set up with."""
        _forbid_spec_attrs(monkeypatch)

        for pagination in (None, Pagination()):
            await list_scripts(None, pagination)


class TestApplierIsBackingAgnostic:
    """Pin the applier's independence from the script seam.

    A hand-written route outside the script framework (the proxied inventory list is
    the next consumer) takes the dependency and applies the result over whatever rows
    it materialized, so the applier must not assume a script type — or drag the script
    seam in as an import.
    """

    def test_applies_over_pydanticrows(self) -> None:
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

        page, total = APPLIER.apply(rows, query, Pagination())

        assert [row.filename for row in page] == ["a-node", "c-node"]
        assert total == matching

    def test_one_applier_serves_repeated_calls_over_mixed_row_types(self) -> None:
        """Keep results stable when a shared applier is reused, since it holds no scratch.

        Module-level appliers are shared across requests, so an interleaving of row
        types, queries, and page windows must not carry state from one call to the next.
        """

        class _Node(BaseModel):
            filename: str
            title: str | None = None
            created_at: int = 0

        dataclass_rows = make_rows(("b.sh", "Beta", 2), ("a.sh", "Alpha", 1))
        model_rows = [_Node(filename="z-node", title="Zeta")]
        query = InMemoryListQuery(sort_key="filename", descending=False, search=None)

        first = APPLIER.apply(dataclass_rows, query, None)
        APPLIER.apply(model_rows, APPLIER.default_query(), Pagination())
        APPLIER.apply(dataclass_rows, APPLIER.build_query("-title", "a"), Pagination())
        second = APPLIER.apply(dataclass_rows, query, None)

        assert [row.filename for row in first[0]] == ["a.sh", "b.sh"]
        assert first == second

    def test_module_does_not_import_the_script_seam(self) -> None:
        """Keep the applier importable without pulling in ``ScriptSource``.

        Walks the module's own import statements rather than scanning its source text,
        so prose mentioning the seam cannot fail the check and a ``TYPE_CHECKING``-only
        import cannot pass it.
        """
        tree = ast.parse(inspect.getsource(list_query_module))
        imported = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        } | {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }

        assert not [name for name in imported if name.endswith("script_source")]

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


"""Test the framework's in-memory list-scripts adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from app.core.db import deps as core_deps
from app.core.db import in_memory_list_query as core_applier
from app.core.db.in_memory_list_query import InMemoryListQuery
from app.core.pagination import Pagination
from app.sep.apps.framework import list_query as list_query_module
from app.sep.apps.framework.list_query import in_memory_list_scripts
from tests.app.list_query_data import list_query_rows, LIST_QUERY_SPEC

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from typing import TypeAlias

    from tests.app.list_query_data import ListQueryRow

# Read off Core's own surface rather than restated, so a name added there is checked
# here without a second edit. Those suites live beside their subjects, in
# tests/app/core/db/.
_MOVED_TO_CORE = tuple(core_applier.__all__) + tuple(core_deps.__all__)

#: The moved names the adapter itself imports at runtime, and so the only ones this
#: module is allowed to leave reachable.
_ADAPTER_NEEDS = frozenset({"apply_in_memory", "default_in_memory_query"})


if TYPE_CHECKING:
    ListScripts: TypeAlias = Callable[
        [InMemoryListQuery | None, Pagination | None],
        Awaitable[tuple[list[ListQueryRow], int]],
    ]


_ADAPTER_ROWS = 3


class TestInMemoryListScripts:
    """Cover the adapter across all four shapes the framework calls it with."""

    @pytest.fixture
    def list_scripts(self) -> ListScripts:
        """Adapt a fixed set of rows through the framework's applier."""
        rows = list_query_rows(
            ("b.sh", "Beta", 2), ("a.sh", "Alpha", 1), ("c.sh", "Gamma", 3)
        )

        async def _materialize() -> list[ListQueryRow]:
            return rows

        return in_memory_list_scripts(_materialize, LIST_QUERY_SPEC)

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


class TestModuleRetainsOnlyTheAdapter:
    """Pin that the generic applier left this module rather than being re-exported.

    A leftover definition, or a re-export beyond what ``_ADAPTER_NEEDS`` records, would
    keep every pre-move import path working — so the relocation would read as done while
    the capability stayed out of reach of the app packages that cannot import
    ``app.sep``.
    """

    def test_exports_only_the_adapter(self) -> None:
        """Publish the adapter alone as this module's surface."""
        assert list_query_module.__all__ == ["in_memory_list_scripts"]

    def test_reachable_moved_names_are_the_adapter_dependencies_only(self) -> None:
        """Leave no moved name reachable here beyond what the adapter itself calls."""
        reachable = {
            name for name in _MOVED_TO_CORE if hasattr(list_query_module, name)
        }

        assert reachable == _ADAPTER_NEEDS

    @pytest.mark.parametrize("name", _MOVED_TO_CORE)
    def test_moved_symbol_is_not_redefined_here(self, name: str) -> None:
        """Resolve a moved name, where the adapter needs one, to its Core module.

        :param name: The moved symbol to check for a local redefinition.
        """
        symbol = getattr(list_query_module, name, None)

        assert symbol is None or symbol.__module__.startswith("app.core.db.")

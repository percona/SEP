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

"""Cover the inventory plugin's entity-dispatching list-query dependency."""

from __future__ import annotations

import inspect

import pytest
from fastapi import status

from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.sep.apps.framework.list_query import InMemoryListQuery
from app.sep.apps.inventory.list_query import (
    ENTITY_LIST_QUERY_SPECS,
    inventory_list_query,
)


class TestInventoryListQuery:
    """Exercise per-entity allowlist dispatch on the shared list dependency."""

    def test_exposes_sort_and_search_params(self) -> None:
        """Declare both ``sort`` and ``search`` for OpenAPI reflection."""
        params = inspect.signature(inventory_list_query).parameters
        assert set(params) == {"entity", "sort", "search"}

    def test_omitted_sort_uses_entity_default(self) -> None:
        """Resolve each entity's own default when ``sort`` is omitted."""
        for entity, spec in ENTITY_LIST_QUERY_SPECS.items():
            query = inventory_list_query(entity=entity, sort=None, search=None)
            expected = InMemoryListQuery.from_sort(spec.default_sort, None)
            assert query == expected

    def test_explicit_sort_and_search_pass_through(self) -> None:
        """Carry a vetted ascending sort key and search term onto the query."""
        query = inventory_list_query(entity="nodes", sort="name", search="db1")
        assert query == InMemoryListQuery(
            sort_key="name", descending=False, search="db1"
        )

    def test_unknown_sort_key_raises_422(self) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422."""
        with pytest.raises(HTTPUnprocessableEntityException) as excinfo:
            inventory_list_query(entity="nodes", sort="bogus", search=None)
        assert excinfo.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "bogus" in str(excinfo.value.detail)

    def test_cross_entity_sort_key_raises_422(self) -> None:
        """Reject a sort key that is legal for schemas but not for nodes."""
        with pytest.raises(HTTPUnprocessableEntityException) as excinfo:
            inventory_list_query(entity="nodes", sort="service_id", search=None)
        assert excinfo.value.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "service_id" in str(excinfo.value.detail)

    def test_unknown_entity_raises_404(self) -> None:
        """Reject an unknown entity segment with HTTP 404."""
        with pytest.raises(HTTPNotFoundException) as excinfo:
            inventory_list_query(entity="widgets", sort=None, search=None)
        assert excinfo.value.status_code == status.HTTP_404_NOT_FOUND

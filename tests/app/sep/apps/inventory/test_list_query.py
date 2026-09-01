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
from types import MappingProxyType

import pytest
from fastapi import status

from app.core.exceptions import (
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.sep.apps.framework.list_query import InMemoryListQuery
from app.sep.apps.inventory import list_query as inventory_list_query_module
from app.sep.apps.inventory.list_query import (
    _ENTITY_LIST_QUERY_APPLIERS,
    ENTITY_LIST_QUERY_SPECS,
    inventory_list_query,
    list_query_upstream_params,
)


class TestInventoryListQuery:
    """Exercise per-entity allowlist dispatch on the shared list dependency."""

    def test_exposes_sort_and_search_params(self) -> None:
        """Declare both ``sort`` and ``search`` for OpenAPI reflection."""
        params = inspect.signature(inventory_list_query).parameters
        assert set(params) == {"entity", "sort", "search"}

    @pytest.mark.parametrize("entity", ENTITY_LIST_QUERY_SPECS)
    def test_omitted_sort_uses_entity_default(self, entity: str) -> None:
        """Resolve each entity's own default when ``sort`` is omitted."""
        spec = ENTITY_LIST_QUERY_SPECS[entity]
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

    def test_schemas_accept_service_id_sort(self) -> None:
        """Accept the schemas-only ``service_id`` sort key on that entity."""
        query = inventory_list_query(entity="schemas", sort="service_id", search=None)
        assert query == InMemoryListQuery(
            sort_key="service_id", descending=False, search=None
        )

    def test_tables_accept_schema_id_sort(self) -> None:
        """Accept the tables-only ``schema_id`` sort key on that entity."""
        query = inventory_list_query(entity="tables", sort="-schema_id", search=None)
        assert query == InMemoryListQuery(
            sort_key="schema_id", descending=True, search=None
        )


class TestEntityListQueryAppliers:
    """Pin that each entity's applier is built at import and only selected per request."""

    def test_covers_every_declared_entity(self) -> None:
        """Bind an applier for every entity the specs declare, and no others."""
        assert set(_ENTITY_LIST_QUERY_APPLIERS) == set(ENTITY_LIST_QUERY_SPECS)

    def test_registry_is_read_only(self) -> None:
        """Expose the registry immutably, so no request can swap an entity's applier."""
        assert isinstance(_ENTITY_LIST_QUERY_APPLIERS, MappingProxyType)

    @pytest.mark.parametrize("entity", ENTITY_LIST_QUERY_SPECS)
    def test_applier_binds_that_entity_spec(self, entity: str) -> None:
        """Bind each applier to its own entity's spec, not a copy of it."""
        assert (
            _ENTITY_LIST_QUERY_APPLIERS[entity].spec is ENTITY_LIST_QUERY_SPECS[entity]
        )

    @pytest.mark.parametrize("entity", ENTITY_LIST_QUERY_SPECS)
    def test_repeated_requests_reuse_the_bound_applier(
        self, entity: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Build no applier per request, across repeated calls.

        Constructing one inside the dependency would satisfy the signature while
        re-resolving the spec once per request, per entity — which is exactly the work
        the module-level registry exists to do once.
        """

        def _boom(spec: object) -> None:
            raise AssertionError(f"applier rebuilt per request for {spec!r}")

        monkeypatch.setattr(
            inventory_list_query_module, "InMemoryListQueryApplier", _boom
        )

        for sort in (None, "name", "-name"):
            assert inventory_list_query(entity=entity, sort=sort, search="db1")


class TestListQueryUpstreamParams:
    """Cover mapping the validated query onto upstream inventory query params."""

    @pytest.mark.parametrize(
        ("query", "expected"),
        [
            (
                InMemoryListQuery(sort_key="name", descending=False, search=None),
                {"sort": "name"},
            ),
            (
                InMemoryListQuery(sort_key="created_at", descending=True, search=None),
                {"sort": "-created_at"},
            ),
            (
                InMemoryListQuery(sort_key="name", descending=False, search="db1"),
                {"sort": "name", "search": "db1"},
            ),
            (
                InMemoryListQuery(sort_key="name", descending=False, search="   "),
                {"sort": "name"},
            ),
        ],
        ids=[
            "ascending_sort_without_search",
            "descending_sort_reprefixes_key",
            "search_term_included_when_present",
            "blank_search_omitted",
        ],
    )
    def test_maps_validated_query_to_upstream_params(
        self,
        query: InMemoryListQuery,
        expected: dict[str, str],
    ) -> None:
        """Map sort direction and blank-search omission onto upstream params."""
        assert list_query_upstream_params(query) == expected

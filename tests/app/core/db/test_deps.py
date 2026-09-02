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


"""Test the in-memory list-query dependency Core exposes to routes."""

from __future__ import annotations

import inspect
from typing import Annotated, Any, TYPE_CHECKING

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy import cast, column, String

from app.core import db as core_db_package
from app.core.db.deps import make_in_memory_list_query_dep
from app.core.db.in_memory_list_query import (
    InMemoryListQuery,
    InMemoryListQueryApplier,
)
from app.core.db.list_query import (
    ListQuerySpec,
    SEARCH_PARAM_DESCRIPTION,
    SORT_PARAM_DESCRIPTION,
)
from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.pagination import Pagination
from app.core.pagination.deps import pagination_dep
from tests.app.list_query_data import (
    list_query_rows,
    LIST_QUERY_SPEC,
    NO_SEARCH_LIST_QUERY_SPEC,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

APPLIER = InMemoryListQueryApplier(LIST_QUERY_SPEC)
NO_SEARCH_APPLIER = InMemoryListQueryApplier(NO_SEARCH_LIST_QUERY_SPEC)


@pytest.fixture(name="dep")
def dep_fixture() -> Callable[..., InMemoryListQuery]:
    """Return the dependency the searchable spec wires.

    :return: A dependency callable built from the searchable spec's applier.
    """
    return make_in_memory_list_query_dep(APPLIER)


class TestMakeInMemoryListQueryDep:
    """Exercise the FastAPI dependency the paginated list route injects."""

    def test_exposed_from_the_package(self) -> None:
        """Re-export the factory beside its SQL sibling on the package surface.

        Both consumers reach ``make_list_query_dep`` through ``app.core.db``, so the
        in-memory factory answering only from the submodule would leave one kind of
        construct with two import homes.
        """
        assert (
            core_db_package.make_in_memory_list_query_dep
            is make_in_memory_list_query_dep
        )

    def test_exposes_sort_and_search_params_when_searchable(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Expose ``sort`` and ``search`` when the spec has searchable columns.

        :param dep: The dependency built from the searchable spec.
        """
        assert set(inspect.signature(dep).parameters) == {"sort", "search"}

    def test_exposes_only_sort_when_no_searchable(self) -> None:
        """Expose only ``sort`` when the spec has no searchable columns."""
        dep = make_in_memory_list_query_dep(NO_SEARCH_APPLIER)
        params = inspect.signature(dep).parameters
        assert set(params) == {"sort"}

    def test_default_sort_resolves_to_spec_default(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Resolve the spec's default sort, honoring its descending prefix.

        :param dep: The dependency built from the searchable spec.
        """
        query = dep(sort=LIST_QUERY_SPEC.default_sort, search=None)
        assert query == InMemoryListQuery(
            sort_key="created_at", descending=True, search=None
        )

    def test_ascending_sort_key_parsed(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Parse a bare (unprefixed) sort key as ascending.

        :param dep: The dependency built from the searchable spec.
        """
        assert dep(sort="filename", search=None).descending is False

    def test_search_term_passed_through(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Carry the raw search term onto the resolved query.

        :param dep: The dependency built from the searchable spec.
        """
        assert dep(sort="filename", search="needle").search == "needle"

    def test_unknown_sort_key_raises_422(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422.

        :param dep: The dependency built from the searchable spec.
        """
        with pytest.raises(HTTPUnprocessableEntityException):
            dep(sort="bogus", search=None)

    def test_unknown_sort_key_with_descending_prefix_raises_422(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Reject an out-of-allowlist descending sort key with HTTP 422.

        :param dep: The dependency built from the searchable spec.
        """
        with pytest.raises(HTTPUnprocessableEntityException):
            dep(sort="-bogus", search=None)

    def test_misdeclared_spec_rejected_before_a_dependency_exists(self) -> None:
        """Reject a misdeclaration where the applier is built, never at a request.

        The factory takes an applier, so a spec that cannot be read off a row fails one
        step earlier than the wiring — there is no dependency to reach a request with.
        """
        spec = ListQuerySpec(
            sortable={"size": cast(column("size"), String)},
            default_sort="size",
            tie_breaker=column("filename"),
        )

        with pytest.raises(ValueError, match="exposes no name"):
            make_in_memory_list_query_dep(InMemoryListQueryApplier(spec))

    def test_each_call_declares_its_own_query_parameters(self) -> None:
        """Hand every route its own parameter declarations, never a shared one.

        FastAPI binds a ``Query`` declaration to each parameter it reflects, so two
        routes built from the same applier must not share one object — the dependency
        is rebuilt per call rather than memoized on the instance.
        """
        first = make_in_memory_list_query_dep(APPLIER)
        second = make_in_memory_list_query_dep(APPLIER)

        assert first is not second
        first_sort = inspect.signature(first).parameters["sort"].default
        second_sort = inspect.signature(second).parameters["sort"].default
        assert first_sort is not second_sort
        assert first_sort.json_schema_extra == second_sort.json_schema_extra

    def test_params_carry_the_allowlist_enum_and_descriptions(
        self, dep: Callable[..., InMemoryListQuery]
    ) -> None:
        """Declare the params through Core, so both paths document one contract.

        :param dep: The dependency built from the searchable spec.
        """
        declarations = {
            name: param.default
            for name, param in inspect.signature(dep).parameters.items()
        }

        assert declarations["sort"].json_schema_extra == {
            "enum": [
                "created_at",
                "-created_at",
                "filename",
                "-filename",
                "title",
                "-title",
            ]
        }
        assert declarations["sort"].description == SORT_PARAM_DESCRIPTION
        assert declarations["search"].description == SEARCH_PARAM_DESCRIPTION


_ROUTE_APP = FastAPI()
_ROUTE_ROWS = list_query_rows(
    ("a.sh", "Alpha", 1), ("b.sh", "Beta", 2), ("c.sh", "Gamma", 3)
)

_search_dep = make_in_memory_list_query_dep(APPLIER)
_no_search_dep = make_in_memory_list_query_dep(NO_SEARCH_APPLIER)


@_ROUTE_APP.get("/scripts")
async def _list_scripts(
    list_query: Annotated[InMemoryListQuery, Depends(_search_dep)],
    pagination: Annotated[Pagination, Depends(pagination_dep)],
) -> dict[str, Any]:
    page, total = APPLIER.apply(_ROUTE_ROWS, list_query, pagination)
    return {"items": [row.filename for row in page], "total": total}


@_ROUTE_APP.get("/scripts-nosearch")
async def _list_scripts_no_search(
    list_query: Annotated[InMemoryListQuery, Depends(_no_search_dep)],
    pagination: Annotated[Pagination, Depends(pagination_dep)],
) -> dict[str, Any]:
    page, total = NO_SEARCH_APPLIER.apply(_ROUTE_ROWS, list_query, pagination)
    return {"items": [row.filename for row in page], "total": total}


@pytest_asyncio.fixture(name="route_client")
async def route_client_fixture() -> AsyncIterator[AsyncClient]:
    """Yield an async client bound to the throwaway in-memory list-query app.

    :return: A client whose lifetime is scoped to the requesting test.
    """
    client = AsyncClient(
        transport=ASGITransport(app=_ROUTE_APP), base_url="http://test"
    )
    try:
        yield client
    finally:
        await client.aclose()


def _route_params(path: str) -> dict[str, dict[str, Any]]:
    """Return the generated OpenAPI query parameters of a route, keyed by name.

    :param path: The route path to read the generated parameters of.
    :return: Each declared query parameter's schema entry, keyed by parameter name.
    """
    return {
        param["name"]: param
        for param in _ROUTE_APP.openapi()["paths"][path]["get"]["parameters"]
    }


class TestInMemoryListQueryDepAtTheRequestBoundary:
    """Pin the in-memory dependency's boundary against the SQL dependency's.

    The direct-call tests above cover resolution; these cover what a client sees —
    the reflected OpenAPI parameters and the rejection body — which is the half a
    request contract can drift on without any unit test noticing.
    """

    def test_search_enabled_route_exposes_both_params(self) -> None:
        """Reflect ``sort`` and ``search`` into the generated OpenAPI."""
        assert {"sort", "search"} <= set(_route_params("/scripts"))

    def test_search_disabled_route_omits_search(self) -> None:
        """Reflect only ``sort`` when the spec declares nothing searchable."""
        names = set(_route_params("/scripts-nosearch"))
        assert "sort" in names
        assert "search" not in names

    def test_params_document_the_allowlist_and_descriptions(self) -> None:
        """Publish the allowlist enum and both descriptions a generated client reads."""
        params = _route_params("/scripts")

        assert params["sort"]["schema"]["enum"] == [
            "created_at",
            "-created_at",
            "filename",
            "-filename",
            "title",
            "-title",
        ]
        assert params["sort"]["description"] == SORT_PARAM_DESCRIPTION
        assert params["search"]["description"] == SEARCH_PARAM_DESCRIPTION

    @pytest.mark.asyncio
    async def test_out_of_allowlist_sort_returns_a_flat_422(
        self, route_client: AsyncClient
    ) -> None:
        """Reject an unvetted sort key with the SQL path's exact 422 body."""
        response = await route_client.get("/scripts", params={"sort": "evil"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json() == {"detail": "Invalid sort key: 'evil'"}

    @pytest.mark.asyncio
    async def test_dunder_sort_key_rejected_at_the_boundary(
        self, route_client: AsyncClient
    ) -> None:
        """Stop an attribute-shaped sort key at the allowlist, before any row read."""
        response = await route_client.get("/scripts", params={"sort": "__class__"})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert response.json() == {"detail": "Invalid sort key: '__class__'"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("term", ["%", "_", "\\", "a%a"])
    async def test_search_metacharacters_match_literally(
        self, route_client: AsyncClient, term: str
    ) -> None:
        """Treat LIKE metacharacters as text, matching the escaped SQL predicate.

        :param term: The metacharacter-bearing term no row contains literally.
        """
        response = await route_client.get("/scripts", params={"search": term})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_padded_search_term_matches_nothing(
        self, route_client: AsyncClient
    ) -> None:
        """Forward a padded term unstripped, so the reply matches a SQL-backed route."""
        response = await route_client.get("/scripts", params={"search": "  beta  "})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_default_sort_applied_when_omitted(
        self, route_client: AsyncClient
    ) -> None:
        """Apply the spec's descending default when the request omits ``sort``."""
        response = await route_client.get("/scripts")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["items"] == ["c.sh", "b.sh", "a.sh"]

    @pytest.mark.asyncio
    async def test_search_filters_and_reports_filtered_total(
        self, route_client: AsyncClient
    ) -> None:
        """Filter by the search term and report the filtered total."""
        response = await route_client.get(
            "/scripts", params={"sort": "filename", "search": "beta"}
        )

        assert response.json() == {"items": ["b.sh"], "total": 1}

    @pytest.mark.asyncio
    async def test_search_param_ignored_where_the_spec_disables_it(
        self, route_client: AsyncClient
    ) -> None:
        """Ignore a ``search`` the route never declared instead of filtering on it."""
        response = await route_client.get(
            "/scripts-nosearch", params={"search": "beta"}
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == len(_ROUTE_ROWS)

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

"""Tests for framework dependency factories in ``deps``."""

import inspect
from collections.abc import AsyncIterator
from typing import Annotated, Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, status
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from app.core.db.list_query import (
    SEARCH_PARAM_DESCRIPTION,
    SORT_PARAM_DESCRIPTION,
)
from app.core.exceptions import HTTPUnprocessableEntityException
from app.core.pagination import Pagination
from app.core.pagination.deps import pagination_dep
from app.core.requests import RemoteAPI
from app.sep.apps.framework import make_parent_resolver, make_task_dep
from app.sep.apps.framework.deps import make_in_memory_list_query_dep
from app.sep.apps.framework.list_query import (
    InMemoryListQuery,
    InMemoryListQueryApplier,
)
from app.sep.deps import get_tasks_api
from app.tasks.models import Task
from tests.app.factories import TaskFactory
from tests.app.sep.apps.framework.list_query_kit import (
    make_rows,
    NO_SEARCH_SPEC,
    SPEC,
)


class TestMakeTaskDep:
    """Test suite for ``make_task_dep``."""

    @pytest.mark.asyncio
    async def test_delegates_to_get_task_by_name_with_owner(self, mocker) -> None:
        """Invoke ``get_task_by_name`` with the bound owner and return its task."""
        task = TaskFactory.build(name="task-1", owner="ARCHIVER")
        get_task_by_name = mocker.patch(
            "app.sep.apps.framework.deps.get_task_by_name",
            new=AsyncMock(return_value=task),
        )
        tasks_api = AsyncMock(spec=RemoteAPI)
        dep = make_task_dep("ARCHIVER")

        result = await dep("task-1", tasks_api)

        assert result is task
        get_task_by_name.assert_awaited_once_with(tasks_api, "task-1", "ARCHIVER")

    def test_distinct_owners_produce_distinct_callables(self) -> None:
        """Build a distinct callable identity per owner for cache/override scoping."""
        archiver_dep = make_task_dep("ARCHIVER")
        checksums_dep = make_task_dep("CHECKSUMS")

        assert archiver_dep is not checksums_dep

    def test_built_callable_resolves_as_fastapi_dependency(self, mocker) -> None:
        """Resolve a route ``Depends(make_task_dep(...))`` through the FastAPI stack."""
        task = TaskFactory.build(name="task-1", owner="ARCHIVER")
        mocker.patch(
            "app.sep.apps.framework.deps.get_task_by_name",
            new=AsyncMock(return_value=task),
        )
        dep = make_task_dep("ARCHIVER")
        app = FastAPI()

        @app.get("/tasks/{task_name}")
        async def _route(resolved: Annotated[Task, Depends(dep)]) -> dict[str, str]:
            return {"name": resolved.name}

        app.dependency_overrides[get_tasks_api] = lambda: AsyncMock(spec=RemoteAPI)
        client = TestClient(app)

        response = client.get("/tasks/task-1")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == {"name": "task-1"}


class TestMakeParentResolver:
    """Test suite for ``make_parent_resolver``."""

    @pytest.mark.asyncio
    async def test_parent_present_refetches_parent(self) -> None:
        """Follow ``data["parent"]`` and re-fetch the parent via ``get_task``."""
        satellite = TaskFactory.build(
            name="child-1",
            owner="ARCHIVER",
            data={"parent": "parent-1"},
        )
        parent = TaskFactory.build(name="parent-1", owner="ARCHIVER")
        get_task = AsyncMock(side_effect=[satellite, parent])
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("child-1", tasks_api)

        assert result is parent
        assert get_task.await_args_list[0].args == ("child-1", tasks_api)
        assert get_task.await_args_list[1].args == ("parent-1", tasks_api)

    @pytest.mark.asyncio
    async def test_parent_absent_returns_original(self) -> None:
        """Return the fetched task unchanged when no parent link is present."""
        task = TaskFactory.build(name="parent-1", owner="ARCHIVER", data={})
        get_task = AsyncMock(return_value=task)
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("parent-1", tasks_api)

        assert result is task
        get_task.assert_awaited_once_with("parent-1", tasks_api)

    @pytest.mark.asyncio
    async def test_parent_name_is_coerced_with_str(self) -> None:
        """Coerce the followed parent name with ``str(...)`` before re-fetching."""
        satellite = TaskFactory.build(
            name="child-1",
            owner="ARCHIVER",
            data={"parent": 42},
        )
        parent = TaskFactory.build(name="42", owner="ARCHIVER")
        get_task = AsyncMock(side_effect=[satellite, parent])
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("child-1", tasks_api)

        assert result is parent
        assert get_task.await_args_list[1].args == ("42", tasks_api)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("parent_value", ["", 0])
    async def test_falsy_parent_returns_original(self, parent_value: str | int) -> None:
        """Treat falsy-but-present ``parent`` values as absent (passthrough)."""
        task = TaskFactory.build(
            name="parent-1",
            owner="ARCHIVER",
            data={"parent": parent_value},
        )
        get_task = AsyncMock(return_value=task)
        tasks_api = AsyncMock(spec=RemoteAPI)
        resolve = make_parent_resolver(get_task)

        result = await resolve("parent-1", tasks_api)

        assert result is task
        get_task.assert_awaited_once_with("parent-1", tasks_api)


APPLIER = InMemoryListQueryApplier(SPEC)
NO_SEARCH_APPLIER = InMemoryListQueryApplier(NO_SEARCH_SPEC)


class TestMakeInMemoryListQueryDep:
    """Exercise the FastAPI dependency the paginated list route injects."""

    def test_exposes_sort_and_search_params_when_searchable(self) -> None:
        """Expose ``sort`` and ``search`` when the spec has searchable columns."""
        params = inspect.signature(make_in_memory_list_query_dep(APPLIER)).parameters
        assert set(params) == {"sort", "search"}

    def test_exposes_only_sort_when_no_searchable(self) -> None:
        """Expose only ``sort`` when the spec has no searchable columns."""
        params = inspect.signature(
            make_in_memory_list_query_dep(NO_SEARCH_APPLIER)
        ).parameters
        assert set(params) == {"sort"}

    def test_default_sort_resolves_to_spec_default(self) -> None:
        """Resolve the spec's default sort, honoring its descending prefix."""
        dep = make_in_memory_list_query_dep(APPLIER)
        query = dep(sort=SPEC.default_sort, search=None)
        assert query == InMemoryListQuery(
            sort_key="created_at", descending=True, search=None
        )

    def test_ascending_sort_key_parsed(self) -> None:
        """Parse a bare (unprefixed) sort key as ascending."""
        dep = make_in_memory_list_query_dep(APPLIER)
        assert dep(sort="filename", search=None).descending is False

    def test_search_term_passed_through(self) -> None:
        """Carry the raw search term onto the resolved query."""
        dep = make_in_memory_list_query_dep(APPLIER)
        assert dep(sort="filename", search="needle").search == "needle"

    def test_unknown_sort_key_raises_422(self) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422."""
        dep = make_in_memory_list_query_dep(APPLIER)
        with pytest.raises(HTTPUnprocessableEntityException):
            dep(sort="bogus", search=None)

    def test_unknown_sort_key_with_descending_prefix_raises_422(self) -> None:
        """Reject an out-of-allowlist descending sort key with HTTP 422."""
        dep = make_in_memory_list_query_dep(APPLIER)
        with pytest.raises(HTTPUnprocessableEntityException):
            dep(sort="-bogus", search=None)

    def test_params_carry_the_allowlist_enum_and_descriptions(self) -> None:
        """Declare the params through Core, so both paths document one contract."""
        declarations = {
            name: param.default
            for name, param in inspect.signature(
                make_in_memory_list_query_dep(APPLIER)
            ).parameters.items()
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

    def test_each_call_declares_its_own_query_parameters(self) -> None:
        """Hand every route its own parameter declarations, never a shared one.

        FastAPI binds a ``Query`` declaration to each parameter it reflects, so two
        routes built from the same applier must not share one object — the
        dependency is rebuilt per call rather than memoized on the instance.
        """
        first = make_in_memory_list_query_dep(APPLIER)
        second = make_in_memory_list_query_dep(APPLIER)

        assert first is not second
        first_sort = inspect.signature(first).parameters["sort"].default
        second_sort = inspect.signature(second).parameters["sort"].default
        assert first_sort is not second_sort
        assert first_sort.json_schema_extra == second_sort.json_schema_extra


_ROUTE_APP = FastAPI()
_ROUTE_ROWS = make_rows(("a.sh", "Alpha", 1), ("b.sh", "Beta", 2), ("c.sh", "Gamma", 3))


@_ROUTE_APP.get("/scripts")
async def _list_scripts(
    list_query: Annotated[
        InMemoryListQuery, Depends(make_in_memory_list_query_dep(APPLIER))
    ],
    pagination: Annotated[Pagination, Depends(pagination_dep)],
) -> dict[str, Any]:
    page, total = APPLIER.apply(_ROUTE_ROWS, list_query, pagination)
    return {"items": [row.filename for row in page], "total": total}


@_ROUTE_APP.get("/scripts-nosearch")
async def _list_scripts_no_search(
    list_query: Annotated[
        InMemoryListQuery, Depends(make_in_memory_list_query_dep(NO_SEARCH_APPLIER))
    ],
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
        """Treat LIKE metacharacters as text, matching the escaped SQL predicate."""
        response = await route_client.get("/scripts", params={"search": term})

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

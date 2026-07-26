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

"""Define tests for the core list-query framework (spec, dependency, predicate)."""

from typing import Annotated

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import col, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from app.core.db import BaseSQLModel
from app.core.db.crud import BaseSQLModelManager
from app.core.db.list_query import (
    build_search_predicate,
    ListQuery,
    ListQuerySpec,
    make_list_query_dep,
    UnknownSortKeyError,
)
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.pagination import PaginatedResponse, Pagination
from app.core.pagination.deps import pagination_dep
from app.core.utils import json_serializer

RESOLVED_ORDER_BY_LENGTH = 2
SEED_NAMES = ("alpha", "bravo", "charlie")


class LQItem(BaseSQLModel, table=True):
    """Represent a test row backing the list-query dependency and applier scenarios."""

    __tablename__ = "test_list_query_item"

    name: str
    category: str


class LQItemManager(BaseSQLModelManager):
    """Manage ``LQItem`` rows through a search-enabled list-query spec."""

    Model = LQItem
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(LQItem.name),
            "created_at": col(LQItem.created_at),
        },
        default_sort="name",
        tie_breaker=col(LQItem.id),
        searchable=[col(LQItem.name)],
    )


NOSEARCH_SPEC = ListQuerySpec(
    sortable={"name": col(LQItem.name)},
    default_sort="name",
    tie_breaker=col(LQItem.id),
)


def _spec(**overrides: object) -> ListQuerySpec:
    """Build a valid ``ListQuerySpec`` for ``LQItem``, applying field overrides."""
    kwargs = {
        "sortable": {"name": col(LQItem.name)},
        "default_sort": "name",
        "tie_breaker": col(LQItem.id),
    }
    kwargs.update(overrides)
    return ListQuerySpec(**kwargs)


class TestListQuerySpecValidation:
    """Cover ``ListQuerySpec`` construction-time validation and immutability."""

    def test_valid_spec_constructs(self) -> None:
        """Accept a spec whose default sort is in the sortable allowlist."""
        spec = _spec()
        assert spec.default_sort == "name"

    def test_default_sort_not_in_allowlist_raises(self) -> None:
        """Reject a default sort key absent from the sortable allowlist."""
        with pytest.raises(ValueError, match="default_sort"):
            _spec(default_sort="missing")

    def test_empty_sortable_key_raises(self) -> None:
        """Reject an empty public sort key."""
        with pytest.raises(ValueError, match="non-empty"):
            _spec(sortable={"": col(LQItem.name)}, default_sort="")

    def test_dash_prefixed_sortable_key_raises(self) -> None:
        """Reject a sortable key beginning with ``-`` (reserved for descending)."""
        with pytest.raises(ValueError, match="must not start with '-'"):
            _spec(sortable={"name": col(LQItem.name), "-bad": col(LQItem.category)})

    def test_missing_tie_breaker_raises(self) -> None:
        """Reject a spec without a tie-breaker column."""
        with pytest.raises(ValueError, match="tie_breaker"):
            _spec(tie_breaker=None)

    def test_non_column_tie_breaker_raises(self) -> None:
        """Reject a tie-breaker that is not a column expression."""
        with pytest.raises(ValueError, match="tie_breaker must be a column"):
            _spec(tie_breaker="id")

    def test_non_column_searchable_entry_raises(self) -> None:
        """Reject a searchable entry that is not a column expression."""
        with pytest.raises(ValueError, match="searchable"):
            _spec(searchable=["name"])

    def test_non_column_sortable_value_raises(self) -> None:
        """Reject a sortable value that is not a column expression."""
        with pytest.raises(ValueError, match="sortable values"):
            _spec(sortable={"name": "name"})

    def test_sortable_coerced_to_immutable_mapping(self) -> None:
        """Coerce a mutable ``sortable`` mapping into a read-only mapping."""
        spec = _spec(sortable={"name": col(LQItem.name)})
        with pytest.raises(TypeError):
            spec.sortable["name"] = col(LQItem.category)  # type: ignore[index]

    def test_searchable_coerced_to_tuple(self) -> None:
        """Coerce a mutable ``searchable`` sequence into an immutable tuple."""
        spec = _spec(searchable=[col(LQItem.name)])
        assert isinstance(spec.searchable, tuple)

    def test_search_enabled_reflects_searchable(self) -> None:
        """Derive ``search_enabled`` from whether ``searchable`` is non-empty."""
        assert _spec(searchable=[col(LQItem.name)]).search_enabled is True
        assert _spec().search_enabled is False


class TestResolveSort:
    """Cover ``ListQuerySpec.resolve_sort`` direction and tie-breaker handling."""

    def test_default_sort_resolves_with_tie_breaker(self) -> None:
        """Resolve the default key into an ordering plus the tie-breaker."""
        order_by = _spec().resolve_sort(None)
        assert len(order_by) == RESOLVED_ORDER_BY_LENGTH
        assert "ASC" in str(order_by[0])
        assert "NULLS LAST" in str(order_by[0])

    def test_descending_prefix_resolves_descending(self) -> None:
        """Resolve a ``-`` prefixed key into a descending ordering."""
        order_by = _spec().resolve_sort("-name")
        assert "DESC" in str(order_by[0])
        assert "NULLS LAST" in str(order_by[0])

    def test_descending_default_sort_resolves_descending(self) -> None:
        """Accept a ``-``-prefixed default sort and resolve it descending."""
        order_by = _spec(default_sort="-name").resolve_sort(None)
        assert "DESC" in str(order_by[0])
        assert "NULLS LAST" in str(order_by[0])

    def test_unknown_key_raises_unknown_sort_key(self) -> None:
        """Raise ``UnknownSortKeyError`` for a key absent from the allowlist."""
        with pytest.raises(UnknownSortKeyError):
            _spec().resolve_sort("evil")

    def test_unknown_descending_key_raises(self) -> None:
        """Raise ``UnknownSortKeyError`` after stripping ``-`` from an unknown key."""
        with pytest.raises(UnknownSortKeyError):
            _spec().resolve_sort("-evil")


class TestBuildSearchPredicate:
    """Cover ``build_search_predicate`` empty-term handling."""

    def test_none_term_returns_none(self) -> None:
        """Return ``None`` for a missing search term."""
        assert build_search_predicate(None, [col(LQItem.name)]) is None

    def test_empty_term_returns_none(self) -> None:
        """Return ``None`` for an empty search term."""
        assert build_search_predicate("", [col(LQItem.name)]) is None

    def test_whitespace_term_returns_none(self) -> None:
        """Return ``None`` for a whitespace-only search term."""
        assert build_search_predicate("   ", [col(LQItem.name)]) is None

    def test_non_empty_term_returns_predicate(self) -> None:
        """Return a predicate for a non-empty search term."""
        assert build_search_predicate("foo", [col(LQItem.name)]) is not None

    def test_no_searchable_columns_returns_none(self) -> None:
        """Return ``None`` when no searchable columns are supplied."""
        assert build_search_predicate("foo", []) is None


class TestMakeListQueryDep:
    """Cover the dependency factory dispatch and construction guards."""

    def test_bare_spec_source_builds_dep(self) -> None:
        """Accept a bare ``ListQuerySpec`` as the dependency source."""
        assert callable(make_list_query_dep(NOSEARCH_SPEC))

    def test_manager_source_builds_dep(self) -> None:
        """Accept a manager class and read its ``list_query_spec``."""
        assert callable(make_list_query_dep(LQItemManager))

    def test_spec_less_manager_raises(self) -> None:
        """Reject a manager class that declares no ``list_query_spec``."""

        class SpecLessManager(BaseSQLModelManager):
            Model = LQItem

        with pytest.raises(ValueError, match="list_query_spec"):
            make_list_query_dep(SpecLessManager)


_SESSION_SENTINEL_APP = FastAPI()

_search_dep = make_list_query_dep(LQItemManager)
_no_search_dep = make_list_query_dep(NOSEARCH_SPEC)


async def _get_lq_session() -> AsyncSession:
    """Raise to force a per-test session-dependency override."""
    raise NotImplementedError


@_SESSION_SENTINEL_APP.get("/lq")
async def _lq_route(
    list_query: Annotated[ListQuery, Depends(_search_dep)],
    session: Annotated[AsyncSession, Depends(_get_lq_session)],
    pagination: Annotated[Pagination, Depends(pagination_dep)],
) -> PaginatedResponse[LQItem]:
    return await LQItemManager.list_query_paginated(
        session, list_query=list_query, pagination=pagination
    )


@_SESSION_SENTINEL_APP.get("/lq-nosearch")
async def _lq_nosearch_route(
    list_query: Annotated[ListQuery, Depends(_no_search_dep)],
    session: Annotated[AsyncSession, Depends(_get_lq_session)],
    pagination: Annotated[Pagination, Depends(pagination_dep)],
) -> PaginatedResponse[LQItem]:
    return await LQItemManager.list_query_paginated(
        session, list_query=list_query, pagination=pagination
    )


@pytest_asyncio.fixture(name="lq_session")
async def lq_session_fixture() -> AsyncSession:
    """Create an isolated SQLite session seeded with ordered, searchable rows."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    try:
        async with async_session_maker() as session:
            for name in SEED_NAMES:
                await LQItemManager.save(session, LQItem(name=name, category="default"))
            yield session
    finally:
        await engine.dispose()


@pytest_asyncio.fixture(name="lq_client")
async def lq_client_fixture(lq_session: AsyncSession) -> AsyncClient:
    """Yield an async client bound to the throwaway list-query app."""

    async def _override_session() -> AsyncSession:
        yield lq_session

    _SESSION_SENTINEL_APP.dependency_overrides[_get_lq_session] = _override_session
    transport = ASGITransport(app=_SESSION_SENTINEL_APP)
    client = AsyncClient(transport=transport, base_url="http://test")
    try:
        yield client
    finally:
        await client.aclose()
        _SESSION_SENTINEL_APP.dependency_overrides = {}


class TestListQueryDependencyOpenAPI:
    """Cover conditional query-parameter exposure in the generated OpenAPI."""

    def test_search_enabled_route_exposes_search_param(self) -> None:
        """Expose ``sort`` and ``search`` on the search-enabled route."""
        params = _SESSION_SENTINEL_APP.openapi()["paths"]["/lq"]["get"]["parameters"]
        names = {param["name"] for param in params}
        assert "sort" in names
        assert "search" in names

    def test_search_disabled_route_omits_search_param(self) -> None:
        """Expose only ``sort`` (not ``search``) on the search-disabled route."""
        params = _SESSION_SENTINEL_APP.openapi()["paths"]["/lq-nosearch"]["get"][
            "parameters"
        ]
        names = {param["name"] for param in params}
        assert "sort" in names
        assert "search" not in names


class TestListQueryDependencyRequests:
    """Cover request-boundary behavior of the list-query dependency and applier."""

    @pytest.mark.asyncio
    async def test_default_sort_applied(self, lq_client: AsyncClient) -> None:
        """Apply the default sort key when ``sort`` is omitted."""
        response = await lq_client.get("/lq")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["name"] for item in body["items"]] == list(SEED_NAMES)
        assert body["total"] == len(SEED_NAMES)

    @pytest.mark.asyncio
    async def test_descending_sort_applied(self, lq_client: AsyncClient) -> None:
        """Apply descending order when a ``-`` prefixed key is requested."""
        response = await lq_client.get("/lq", params={"sort": "-name"})
        assert response.status_code == status.HTTP_200_OK
        names = [item["name"] for item in response.json()["items"]]
        assert names == list(reversed(SEED_NAMES))

    @pytest.mark.asyncio
    async def test_out_of_allowlist_sort_returns_422(
        self, lq_client: AsyncClient
    ) -> None:
        """Reject an out-of-allowlist sort key with HTTP 422."""
        response = await lq_client.get("/lq", params={"sort": "evil"})
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_search_filters_and_reports_filtered_total(
        self, lq_client: AsyncClient
    ) -> None:
        """Filter rows by search and report the filtered total, not the page size."""
        response = await lq_client.get("/lq", params={"search": "alp"})
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert [item["name"] for item in body["items"]] == ["alpha"]
        assert body["total"] == 1

    @pytest.mark.asyncio
    async def test_empty_search_returns_all_rows(self, lq_client: AsyncClient) -> None:
        """Apply no predicate for an empty search term."""
        response = await lq_client.get("/lq", params={"search": ""})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == len(SEED_NAMES)

    @pytest.mark.asyncio
    async def test_search_param_ignored_on_search_disabled_route(
        self, lq_client: AsyncClient
    ) -> None:
        """Ignore a ``search`` param on a route whose spec disables search."""
        response = await lq_client.get("/lq-nosearch", params={"search": "alp"})
        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == len(SEED_NAMES)

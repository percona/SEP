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

import inspect
from collections.abc import Callable
from typing import Annotated

import pytest
import pytest_asyncio
from fastapi import Depends, FastAPI, params, status
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects import mysql
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import col, select, SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from app.core.db import BaseSQLModel
from app.core.db.crud import BaseSQLModelManager
from app.core.db.list_query import (
    build_search_predicate,
    ListQuery,
    ListQuerySpec,
    make_list_query_dep,
    make_query_param_dep,
    SEARCH_PARAM_DESCRIPTION,
    SORT_PARAM_DESCRIPTION,
    UnknownSortKeyError,
)
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.exceptions import HTTPUnprocessableEntityException
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

    @pytest.mark.parametrize("raw_sort", [None, "-name"], ids=["asc", "desc"])
    def test_resolved_ordering_renders_mysql_isnull_idiom(self, raw_sort) -> None:
        """Emit MySQL's ``ISNULL`` idiom instead of the unparsable ``NULLS LAST``."""
        order_by = _spec().resolve_sort(raw_sort)

        rendered = str(
            select(col(LQItem.id)).order_by(*order_by).compile(dialect=mysql.dialect())
        )

        assert "NULLS LAST" not in rendered
        assert "ISNULL(" in rendered
        assert rendered.rstrip().endswith("id ASC")


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


def _record_build(
    calls: list[tuple[ListQuerySpec, str, str | None]],
) -> Callable[[ListQuerySpec, str, str | None], None]:
    """Return a builder recording the arguments the dependency shape hands it.

    :param calls: The list each invocation appends its ``(spec, sort, search)`` to.
    :return: A builder usable as the dependency's value-object factory.
    """

    def build(spec: ListQuerySpec, sort: str, search: str | None) -> None:
        calls.append((spec, sort, search))

    return build


class TestMakeQueryParamDep:
    """Cover the dependency shape both list-query factories are built from."""

    def test_builder_receives_the_spec_and_both_request_values(self) -> None:
        """Hand the bound spec and the request's sort and search to the builder."""
        spec = _spec(searchable=[col(LQItem.name)])
        calls: list[tuple[ListQuerySpec, str, str | None]] = []

        make_query_param_dep(spec, _record_build(calls))(sort="name", search="needle")

        assert calls == [(spec, "name", "needle")]

    def test_search_disabled_builder_receives_no_term(self) -> None:
        """Pass ``None`` as the term when the spec declares nothing searchable."""
        spec = _spec()
        calls: list[tuple[ListQuerySpec, str, str | None]] = []

        make_query_param_dep(spec, _record_build(calls))(sort="name")

        assert calls == [(spec, "name", None)]

    def test_unknown_sort_key_maps_to_422(self) -> None:
        """Translate the builder's ``UnknownSortKeyError`` into a flat 422 detail."""

        def build(spec: ListQuerySpec, sort: str, search: str | None) -> None:
            raise UnknownSortKeyError(sort)

        dep = make_query_param_dep(_spec(), build)

        with pytest.raises(HTTPUnprocessableEntityException) as exc_info:
            dep(sort="evil")

        assert exc_info.value.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        assert exc_info.value.detail == "Invalid sort key: 'evil'"

    def test_builder_value_object_is_returned_unchanged(self) -> None:
        """Return exactly what the builder produced, so each path keeps its own type."""
        sentinel = object()

        def build(spec: ListQuerySpec, sort: str, search: str | None) -> object:
            return sentinel

        dep = make_query_param_dep(_spec(), build)

        assert dep(sort="name") is sentinel

    def test_detail_reports_the_rejected_key_not_the_raw_request_value(self) -> None:
        """Report the key the error carries, which is the request value minus any ``-``."""

        def build(spec: ListQuerySpec, sort: str, search: str | None) -> None:
            raise UnknownSortKeyError(sort.removeprefix("-"))

        dep = make_query_param_dep(_spec(), build)

        with pytest.raises(HTTPUnprocessableEntityException) as exc_info:
            dep(sort="-evil")

        assert exc_info.value.detail == "Invalid sort key: 'evil'"

    def test_rejection_chains_the_original_error(self) -> None:
        """Keep the ``UnknownSortKeyError`` as the 422's cause for the traceback."""

        def build(spec: ListQuerySpec, sort: str, search: str | None) -> None:
            raise UnknownSortKeyError(sort)

        dep = make_query_param_dep(_spec(), build)

        with pytest.raises(HTTPUnprocessableEntityException) as exc_info:
            dep(sort="evil")

        assert isinstance(exc_info.value.__cause__, UnknownSortKeyError)

    def test_unrelated_builder_failure_propagates(self) -> None:
        """Leave a non-sort failure alone rather than reporting it as a bad sort key."""

        def build(spec: ListQuerySpec, sort: str, search: str | None) -> None:
            raise ValueError("row mismatch")

        dep = make_query_param_dep(_spec(), build)

        with pytest.raises(ValueError, match="row mismatch"):
            dep(sort="name")

    @pytest.mark.parametrize(
        ("searchable", "expected"),
        [([col(LQItem.name)], {"sort", "search"}), ([], {"sort"})],
        ids=["search-enabled", "search-disabled"],
    )
    def test_declares_only_the_enabled_params(self, searchable, expected) -> None:
        """Declare ``search`` only for a spec whose searchable set is non-empty."""
        dep = make_query_param_dep(_spec(searchable=searchable), _record_build([]))

        assert set(inspect.signature(dep).parameters) == expected

    def test_each_dep_gets_its_own_param_declarations(self) -> None:
        """Build a fresh declaration per dependency, as FastAPI binds one per param."""
        spec = _spec(searchable=[col(LQItem.name)])
        deps = [make_query_param_dep(spec, _record_build([])) for _ in range(2)]

        defaults = [inspect.signature(dep).parameters["sort"].default for dep in deps]

        assert all(isinstance(default, params.Query) for default in defaults)
        assert defaults[0] is not defaults[1]

    def test_signature_is_the_functions_own(self) -> None:
        """Reflect a statically-defined signature, never a synthesized one.

        A dynamically built signature has silently broken OpenAPI reflection in this
        repo before, which is why the shape is two hand-written inner functions.
        """
        dep = make_query_param_dep(_spec(), _record_build([]))

        assert "__signature__" not in vars(dep)
        assert not hasattr(dep, "__wrapped__")


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

    def test_sort_param_publishes_the_allowlist_as_an_enum(self) -> None:
        """Publish both directions of every sortable key, so a client can discover them."""
        params = _SESSION_SENTINEL_APP.openapi()["paths"]["/lq"]["get"]["parameters"]
        sort = next(param for param in params if param["name"] == "sort")

        assert sort["schema"]["enum"] == [
            "created_at",
            "-created_at",
            "name",
            "-name",
        ]

    def test_query_params_carry_descriptions(self) -> None:
        """Document both parameters, so the generated client is not bare strings."""
        params = _SESSION_SENTINEL_APP.openapi()["paths"]["/lq"]["get"]["parameters"]
        described = {
            param["name"]: param.get("description")
            for param in params
            if param["name"] in {"sort", "search"}
        }

        assert described == {
            "sort": SORT_PARAM_DESCRIPTION,
            "search": SEARCH_PARAM_DESCRIPTION,
        }


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
    async def test_rejected_sort_names_the_key_in_a_flat_detail(
        self, lq_client: AsyncClient
    ) -> None:
        """Report the rejected key in a flat ``detail`` body, not a validation list."""
        response = await lq_client.get("/lq", params={"sort": "evil"})

        assert response.json() == {"detail": "Invalid sort key: 'evil'"}

    @pytest.mark.asyncio
    async def test_rejected_descending_key_is_reported_without_its_prefix(
        self, lq_client: AsyncClient
    ) -> None:
        """Strip the direction marker from the reported key, as the allowlist holds it."""
        response = await lq_client.get("/lq", params={"sort": "-evil"})

        assert response.json() == {"detail": "Invalid sort key: 'evil'"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "sort",
        ["", "-", "name ", " name", "NAME", "-evil"],
        ids=[
            "empty",
            "bare-dash",
            "trailing-space",
            "leading-space",
            "case",
            "unknown",
        ],
    )
    async def test_sort_keys_are_matched_exactly(
        self, lq_client: AsyncClient, sort: str
    ) -> None:
        """Match allowlist keys byte-for-byte: nothing is trimmed, folded, or defaulted."""
        response = await lq_client.get("/lq", params={"sort": sort})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.asyncio
    async def test_sort_injection_attempt_never_reaches_the_query(
        self, lq_client: AsyncClient
    ) -> None:
        """Reject a SQL-shaped sort value and leave the table listable afterwards."""
        rejected = await lq_client.get(
            "/lq", params={"sort": f"name); DROP TABLE {LQItem.__tablename__}; --"}
        )
        assert rejected.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

        surviving = await lq_client.get("/lq")
        assert surviving.json()["total"] == len(SEED_NAMES)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "term", ["%", "_", "\\", "a%a"], ids=["pct", "us", "esc", "mixed"]
    )
    async def test_search_wildcards_match_literally(
        self, lq_client: AsyncClient, term: str
    ) -> None:
        """Escape LIKE metacharacters, so a wildcard cannot widen the filtered total."""
        response = await lq_client.get("/lq", params={"search": term})

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["total"] == 0

    @pytest.mark.asyncio
    async def test_repeated_sort_param_takes_the_last_value(
        self, lq_client: AsyncClient
    ) -> None:
        """Resolve a repeated ``sort`` to its last value rather than erroring."""
        response = await lq_client.get(
            "/lq", params=[("sort", "name"), ("sort", "-name")]
        )

        assert response.status_code == status.HTTP_200_OK
        names = [item["name"] for item in response.json()["items"]]
        assert names == list(reversed(SEED_NAMES))

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

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

"""Define tests for CRUD pagination helpers."""

from collections.abc import AsyncGenerator
from datetime import datetime, timedelta, UTC

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import col, Relationship, SQLModel
from sqlmodel import Field as SQLField
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from app.core.db import BaseSQLModel
from app.core.db.crud import BaseSQLModelManager
from app.core.db.list_query import build_search_predicate, ListQuery, ListQuerySpec
from app.core.db.models import BaseUUIDSQLModel
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.pagination import DEFAULT_PAGINATION_LIMIT, PaginatedResponse, Pagination
from app.core.utils import json_serializer
from tests.app.db_schema import apply_schema

MATCHING_ITEM_TOTAL = 3
SELECT_RELATED_PAGE_LIMIT = 2
RESOLVED_ORDER_BY_LENGTH = 2
SEARCH_MATCH_TOTAL = 2
INVALID_PAGINATION_VALUE = -1
UNPAGINATED_ITEM_TOTAL = 55
# first() is invoked twice on the conflict path: existence check, then refetch.
CONFLICT_PATH_FIRST_CALLS = 2


class PaginationParent(BaseSQLModel, table=True):
    """Test parent model for pagination select-related scenarios."""

    __tablename__ = "test_pagination_parent"

    name: str
    items: list["PaginationItem"] = Relationship(back_populates="parent")


class PaginationItem(BaseSQLModel, table=True):
    """Test child model used for CRUD pagination checks."""

    __tablename__ = "test_pagination_item"

    name: str
    category: str
    parent_id: int | None = SQLField(
        default=None,
        foreign_key="test_pagination_parent.id",
    )
    parent: PaginationParent | None = Relationship(back_populates="items")


class PaginationParentManager(BaseSQLModelManager):
    """Manager for test pagination parents."""

    Model = PaginationParent


class PaginationItemManager(BaseSQLModelManager):
    """Manager for test pagination items without explicit ordering."""

    Model = PaginationItem


class PaginationItemByNameManager(BaseSQLModelManager):
    """Manage test pagination items with a spec default sort by name."""

    Model = PaginationItem
    list_query_spec = ListQuerySpec(
        sortable={"name": col(PaginationItem.name)},
        default_sort="name",
        tie_breaker=col(PaginationItem.id),
    )


class PaginationItemSpecManager(BaseSQLModelManager):
    """Manage test pagination items through a declared list-query spec."""

    Model = PaginationItem
    list_query_spec = ListQuerySpec(
        sortable={
            "name": col(PaginationItem.name),
            "category": col(PaginationItem.category),
            "parent_id": col(PaginationItem.parent_id),
        },
        default_sort="name",
        tie_breaker=col(PaginationItem.id),
        searchable=[col(PaginationItem.name)],
    )


class UniqueKeyModel(BaseSQLModel, table=True):
    """Test model with a unique key used for ``get_or_create`` race checks."""

    __tablename__ = "test_unique_key"

    key: str = SQLField(unique=True, index=True)
    label: str = "default"


class UniqueKeyManager(BaseSQLModelManager):
    """Manager for the unique-keyed test model."""

    Model = UniqueKeyModel


class UniqueKeyUUIDModel(BaseUUIDSQLModel, table=True):
    """UUID-PK test model used for the ``get_or_create`` PK-preserved branch."""

    __tablename__ = "test_unique_key_uuid"

    key: str = SQLField(unique=True, index=True)
    label: str = "default"


class UniqueKeyUUIDManager(BaseSQLModelManager):
    """Manager for the UUID-keyed test model."""

    Model = UniqueKeyUUIDModel


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncGenerator[AsyncSession, None]:
    """Create an isolated async database session for CRUD pagination tests."""
    # scaffolding-dup-ok: this duplication predates the change that
    # re-annotated the fixture's return type; promoting it against
    # its sibling bootstrap is a cross-tree refactor of its own.
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await apply_schema(conn, SQLModel.metadata)
    async_session_maker = get_async_session_maker_from_engine(engine)
    try:
        async with async_session_maker() as session:
            yield session
    finally:
        await engine.dispose()


async def _create_parent(session: AsyncSession, name: str) -> PaginationParent:
    """Create and persist a pagination parent."""
    return await PaginationParentManager.save(
        session,
        PaginationParent(name=name),
    )


async def _create_item(
    session: AsyncSession,
    *,
    name: str,
    created_at: datetime,
    category: str = "default",
    parent_id: int | None = None,
) -> PaginationItem:
    """Create and persist a pagination item with deterministic timestamps."""
    return await PaginationItemManager.save(
        session,
        PaginationItem(
            name=name,
            category=category,
            parent_id=parent_id,
            created_at=created_at,
        ),
    )


class TestBaseSQLModelManagerPagination:
    """Test pagination behavior for `BaseSQLModelManager`."""

    @pytest.mark.asyncio
    async def test_list_without_pagination_returns_all_items(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert ``list()`` without pagination returns every matching record."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(UNPAGINATED_ITEM_TOTAL):
            await _create_item(
                session,
                name=f"item-{index}",
                created_at=base_time + timedelta(minutes=index),
            )

        result = await PaginationItemManager.list(session)

        assert len(result) == UNPAGINATED_ITEM_TOTAL
        assert [item.name for item in result[:3]] == ["item-54", "item-53", "item-52"]
        assert result[-1].name == "item-0"

    @pytest.mark.asyncio
    async def test_list_with_explicit_limit_applies_pagination(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert ``list()`` with an explicit limit paginates in ``created_at`` order."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(UNPAGINATED_ITEM_TOTAL):
            await _create_item(
                session,
                name=f"item-{index}",
                created_at=base_time + timedelta(minutes=index),
            )

        result = await PaginationItemManager.list(
            session, limit=DEFAULT_PAGINATION_LIMIT
        )

        assert len(result) == DEFAULT_PAGINATION_LIMIT
        assert result[0].name == "item-54"
        assert result[-1].name == "item-5"

    @pytest.mark.asyncio
    async def test_list_applies_offset_and_limit(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert custom offset and limit return the expected page slice."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(5):
            await _create_item(
                session,
                name=f"item-{index}",
                created_at=base_time + timedelta(minutes=index),
            )

        result = await PaginationItemManager.list(session, offset=1, limit=2)

        assert [item.name for item in result] == ["item-3", "item-2"]

    @pytest.mark.asyncio
    async def test_list_offset_beyond_total_returns_empty_list(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert an out-of-range offset returns an empty list."""
        await _create_item(
            session,
            name="item-0",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        result = await PaginationItemManager.list(session, offset=10, limit=5)

        assert result == []

    @pytest.mark.asyncio
    async def test_list_limit_zero_returns_all_items(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert limit zero disables the limit and returns all records."""
        await _create_item(
            session,
            name="item-0",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        result = await PaginationItemManager.list(session, limit=0)

        assert len(result) == 1
        assert result[0].name == "item-0"

    @pytest.mark.asyncio
    async def test_list_paginated_returns_items_total_offset_and_limit(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert paginated responses include metadata and filtered totals."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        await _create_item(
            session,
            name="other-category",
            category="other",
            created_at=base_time,
        )
        for index in range(MATCHING_ITEM_TOTAL):
            await _create_item(
                session,
                name=f"match-{index}",
                category="target",
                created_at=base_time + timedelta(minutes=index + 1),
            )

        result = await PaginationItemManager.list_paginated(
            session,
            category="target",
            pagination=Pagination(offset=1, limit=1),
        )

        assert isinstance(result, PaginatedResponse)
        assert result.total == MATCHING_ITEM_TOTAL
        assert result.offset == 1
        assert result.limit == 1
        assert [item.name for item in result.items] == ["match-1"]

    @pytest.mark.asyncio
    async def test_list_paginated_supports_select_related(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert pagination still works when joined relationships are loaded."""
        parent = await _create_parent(session, "parent-1")
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(MATCHING_ITEM_TOTAL):
            await _create_item(
                session,
                name=f"item-{index}",
                created_at=base_time + timedelta(minutes=index),
                parent_id=parent.id,
            )

        result = await PaginationItemManager.list_paginated(
            session,
            select_related=[PaginationItem.parent],
            pagination=Pagination(offset=0, limit=SELECT_RELATED_PAGE_LIMIT),
        )

        assert result.total == MATCHING_ITEM_TOTAL
        assert len(result.items) == SELECT_RELATED_PAGE_LIMIT
        assert all(item.parent is not None for item in result.items)
        assert result.items[0].parent.name == "parent-1"

    @pytest.mark.asyncio
    async def test_list_paginated_deduplicates_collection_joins(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert collection joinedloads do not under-fill paginated pages.

        Without the primary-key subquery fix, a naive ``LIMIT 1`` query combined
        with a ``joinedload`` of the ``items`` collection multiplies rows and
        drops entities after ``result.unique()`` runs, causing the page to be
        under-filled.
        """
        parent = await _create_parent(session, "parent-1")
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(MATCHING_ITEM_TOTAL):
            await _create_item(
                session,
                name=f"item-{index}",
                created_at=base_time + timedelta(minutes=index),
                parent_id=parent.id,
            )

        result = await PaginationParentManager.list_paginated(
            session,
            select_related=[PaginationParent.items],
            pagination=Pagination(offset=0, limit=1),
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "parent-1"
        assert len(result.items[0].items) == MATCHING_ITEM_TOTAL

    @pytest.mark.asyncio
    async def test_spec_default_sort_overrides_created_at_fallback(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert managers with a spec default sort ignore the fallback ordering."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        await _create_item(
            session,
            name="zeta",
            created_at=base_time + timedelta(minutes=3),
        )
        await _create_item(
            session,
            name="alpha",
            created_at=base_time + timedelta(minutes=2),
        )
        await _create_item(
            session,
            name="beta",
            created_at=base_time + timedelta(minutes=1),
        )

        result = await PaginationItemByNameManager.list(session, limit=10)

        assert [item.name for item in result] == ["alpha", "beta", "zeta"]

    @pytest.mark.asyncio
    async def test_created_at_fallback_tie_breaks_on_primary_key(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert the ``created_at`` fallback tie-breaks deterministically on PK.

        ``utc_now()`` has second resolution, so rows frequently share a
        ``created_at``. The fallback ordering appends ``id DESC`` so ties resolve
        deterministically (newest-inserted first) instead of relying on an
        unstable order that can skip or duplicate rows across paginated pages.
        """
        shared_time = datetime(2026, 1, 1, tzinfo=UTC)
        first = await _create_item(session, name="first", created_at=shared_time)
        second = await _create_item(session, name="second", created_at=shared_time)
        third = await _create_item(session, name="third", created_at=shared_time)

        result = await PaginationItemManager.list(session)

        # All share created_at, so the id DESC tie-breaker drives the order
        # (highest/newest id first).
        assert [item.id for item in result] == [third.id, second.id, first.id]
        assert [item.name for item in result] == ["third", "second", "first"]


class TestGetOrCreate:
    """Test ``BaseSQLModelManager.get_or_create`` including the conflict path."""

    @pytest.mark.asyncio
    async def test_creates_new_row(self, session: AsyncSession) -> None:
        """A fresh key inserts the row, reports ``created=True``, and fills defaults."""
        instance, created = await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="alpha", label="first"),
            filter_include={"key"},
        )

        assert created is True
        assert instance.id is not None
        assert instance.key == "alpha"
        assert instance.label == "first"
        # Python-side default_factory (created_at) must be materialized on insert.
        assert instance.created_at is not None
        assert instance.updated_at is None
        assert await UniqueKeyManager.count(session) == 1

    @pytest.mark.asyncio
    async def test_returns_existing_row_without_duplicating(
        self, session: AsyncSession
    ) -> None:
        """An existing key short-circuits to the stored row with ``created=False``."""
        first_instance, first_created = await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="beta", label="original"),
            filter_include={"key"},
        )
        assert first_created is True

        second_instance, second_created = await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="beta", label="ignored"),
            filter_include={"key"},
        )

        assert second_created is False
        assert second_instance.id == first_instance.id
        assert second_instance.label == "original"
        assert await UniqueKeyManager.count(session) == 1

    @pytest.mark.asyncio
    async def test_conflict_refetches_winning_row_without_raising(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A row created after the ``first()`` check no longer 400s; it refetches.

        Simulates the TOCTOU race: a concurrent winner has already committed the
        row, but this call's existence check ran before that commit. ``first()``
        is patched to return ``None`` on its first invocation (the existence
        check) and delegate afterwards (the refetch), forcing the upsert branch
        to hit the duplicate and resolve idempotently.
        """
        winner = await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="gamma", label="winner"),
            filter_include={"key"},
        )
        winner_instance = winner[0]

        original_first = UniqueKeyManager.first.__func__
        calls = {"count": 0}

        async def first_returns_none_then_delegates(
            cls: type[UniqueKeyManager], *args: object, **kwargs: object
        ) -> UniqueKeyModel | None:
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return await original_first(cls, *args, **kwargs)

        monkeypatch.setattr(
            UniqueKeyManager,
            "first",
            classmethod(first_returns_none_then_delegates),
        )

        instance, created = await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="gamma", label="loser"),
            filter_include={"key"},
        )

        assert created is False
        assert instance.id == winner_instance.id
        assert instance.label == "winner"
        assert calls["count"] == CONFLICT_PATH_FIRST_CALLS
        assert await UniqueKeyManager.count(session) == 1

    @pytest.mark.asyncio
    async def test_creates_uuid_keyed_row(self, session: AsyncSession) -> None:
        """A UUID-PK model keeps its factory-assigned PK on the upsert path."""
        instance, created = await UniqueKeyUUIDManager.get_or_create(
            session,
            UniqueKeyUUIDModel(key="alpha", label="first"),
            filter_include={"key"},
        )

        assert created is True
        # default_factory(uuid4) supplies a non-null PK; the upsert must preserve it
        # (the values.pop branch only fires for None autoincrement PKs).
        assert instance.id is not None
        assert instance.key == "alpha"
        assert instance.created_at is not None
        assert await UniqueKeyUUIDManager.count(session) == 1

    @pytest.mark.asyncio
    async def test_uuid_conflict_refetches_winning_row_without_raising(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A UUID-keyed conflict resolves idempotently despite differing PKs.

        Two racers generate distinct UUID PKs but share the unique business key, so
        the conflict fires on ``key`` (not the PK). The loser must refetch the
        winner's row and report ``created=False``.
        """
        winner_instance, _ = await UniqueKeyUUIDManager.get_or_create(
            session,
            UniqueKeyUUIDModel(key="gamma", label="winner"),
            filter_include={"key"},
        )

        original_first = UniqueKeyUUIDManager.first.__func__
        calls = {"count": 0}

        async def first_returns_none_then_delegates(
            cls: type[UniqueKeyUUIDManager], *args: object, **kwargs: object
        ) -> UniqueKeyUUIDModel | None:
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return await original_first(cls, *args, **kwargs)

        monkeypatch.setattr(
            UniqueKeyUUIDManager,
            "first",
            classmethod(first_returns_none_then_delegates),
        )

        instance, created = await UniqueKeyUUIDManager.get_or_create(
            session,
            UniqueKeyUUIDModel(key="gamma", label="loser"),
            filter_include={"key"},
        )

        assert created is False
        assert instance.id == winner_instance.id
        assert instance.label == "winner"
        assert await UniqueKeyUUIDManager.count(session) == 1

    @pytest.mark.asyncio
    async def test_applies_extra_fields_on_insert(self, session: AsyncSession) -> None:
        """``extra_fields`` are written to the upserted row, not dropped."""
        instance, created = await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="delta"),
            filter_include={"key"},
            label="from-extra-fields",
        )

        assert created is True
        assert instance.label == "from-extra-fields"
        refetched = await UniqueKeyManager.first(session, key="delta")
        assert refetched.label == "from-extra-fields"

    @pytest.mark.asyncio
    async def test_conflict_with_filter_outside_unique_constraint_raises(
        self, session: AsyncSession, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A refetch that cannot match the winning row fails loud, not silently.

        When ``filter_include`` covers a column outside the unique constraint that
        differs between racers (here ``label``), the loser's refetch finds no row.
        The helper must raise a descriptive error at the source rather than return
        ``(None, False)`` and defer a confusing crash to the caller.
        """
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="epsilon", label="winner"),
        )

        original_first = UniqueKeyManager.first.__func__
        calls = {"count": 0}

        async def first_returns_none_then_delegates(
            cls: type[UniqueKeyManager], *args: object, **kwargs: object
        ) -> UniqueKeyModel | None:
            calls["count"] += 1
            if calls["count"] == 1:
                return None
            return await original_first(cls, *args, **kwargs)

        monkeypatch.setattr(
            UniqueKeyManager,
            "first",
            classmethod(first_returns_none_then_delegates),
        )

        with pytest.raises(RuntimeError, match="unique conflict"):
            await UniqueKeyManager.get_or_create(
                session,
                UniqueKeyModel(key="epsilon", label="loser"),
            )

        assert await UniqueKeyManager.count(session) == 1


class TestGetOrderingSpecShim:
    """Cover ``_get_ordering`` derive-from-spec and default-fallback behavior."""

    def test_spec_manager_derives_default_sort_ordering(self) -> None:
        """Derive ``[default NULLS LAST, tie-breaker]`` when a spec is declared."""
        ordering = list(PaginationItemSpecManager._get_ordering())

        assert len(ordering) == RESOLVED_ORDER_BY_LENGTH
        assert "name" in str(ordering[0])
        assert "ASC" in str(ordering[0])
        assert "NULLS LAST" in str(ordering[0])
        assert ".id" in str(ordering[1])

    def test_spec_less_manager_keeps_created_at_fallback(self) -> None:
        """Keep the ``created_at``-desc fallback byte-identical for spec-less managers."""
        ordering = list(PaginationItemManager._get_ordering())

        assert len(ordering) == RESOLVED_ORDER_BY_LENGTH
        assert "created_at" in str(ordering[0])
        assert "DESC" in str(ordering[0])
        assert ".id" in str(ordering[1])
        assert "DESC" in str(ordering[1])


class TestOrderByOverride:
    """Cover the per-call ``order_by`` override threaded through ``_select``."""

    @pytest.mark.asyncio
    async def test_order_by_overrides_default_ordering(
        self, session: AsyncSession
    ) -> None:
        """Apply the explicit ``order_by`` override in place of the fallback ordering."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for offset, name in enumerate(("zeta", "alpha", "beta")):
            await _create_item(
                session,
                name=name,
                created_at=base_time + timedelta(minutes=offset),
            )

        result = await PaginationItemManager.list(
            session, order_by=[col(PaginationItem.name).asc()]
        )

        assert [item.name for item in result] == ["alpha", "beta", "zeta"]

    @pytest.mark.asyncio
    async def test_order_by_override_applies_in_select_related_pagination(
        self, session: AsyncSession
    ) -> None:
        """Apply the override to both the pk-query and the final select_related query.

        The created-at order is the reverse of the name order, so a page taken by
        the fallback ordering would select a different id set than the override
        does. Asserting the exact page proves the override reaches the pk-query.
        """
        parent = await _create_parent(session, "parent-1")
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        await _create_item(
            session,
            name="charlie",
            created_at=base_time + timedelta(minutes=3),
            parent_id=parent.id,
        )
        await _create_item(
            session,
            name="alpha",
            created_at=base_time + timedelta(minutes=2),
            parent_id=parent.id,
        )
        await _create_item(
            session,
            name="bravo",
            created_at=base_time + timedelta(minutes=1),
            parent_id=parent.id,
        )

        result = await PaginationItemManager.list(
            session,
            select_related=[PaginationItem.parent],
            order_by=[col(PaginationItem.name).asc()],
            offset=0,
            limit=SELECT_RELATED_PAGE_LIMIT,
        )

        assert [item.name for item in result] == ["alpha", "bravo"]
        assert all(item.parent is not None for item in result)


class TestListQueryPaginated:
    """Cover ``list_query_paginated`` filtered-total behavior on SQLite."""

    @pytest.mark.asyncio
    async def test_search_predicate_drives_filtered_total(
        self, session: AsyncSession
    ) -> None:
        """Report the search-filtered total, not the page size or the grand total."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for index in range(SEARCH_MATCH_TOTAL):
            await _create_item(
                session,
                name=f"match-{index}",
                created_at=base_time + timedelta(minutes=index),
            )
        for index in range(MATCHING_ITEM_TOTAL):
            await _create_item(
                session,
                name=f"other-{index}",
                created_at=base_time + timedelta(minutes=index + 2),
            )

        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort(None)),
            search_predicate=build_search_predicate("match", spec.searchable),
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=1),
        )

        assert result.total == SEARCH_MATCH_TOTAL
        assert len(result.items) == 1

    @pytest.mark.asyncio
    async def test_base_and_search_clauses_are_shared_by_count_and_list(
        self, session: AsyncSession
    ) -> None:
        """Fold the base whereclause and search into the clauses feeding both queries."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        await _create_item(
            session, name="keep-a", category="target", created_at=base_time
        )
        await _create_item(
            session,
            name="keep-b",
            category="other",
            created_at=base_time + timedelta(minutes=1),
        )
        await _create_item(
            session,
            name="drop-a",
            category="target",
            created_at=base_time + timedelta(minutes=2),
        )

        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort(None)),
            search_predicate=build_search_predicate("keep", spec.searchable),
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            session,
            col(PaginationItem.category) == "target",
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert result.total == 1
        assert [item.name for item in result.items] == ["keep-a"]


@pytest.mark.postgres
class TestListQueryPaginatedPostgres:
    """Cover engine-sensitive NULLS LAST ordering and native escaped ILIKE."""

    @pytest.mark.asyncio
    async def test_ascending_nullable_sort_places_nulls_last(
        self, postgres_session: AsyncSession
    ) -> None:
        """Keep NULLs last in ascending order and tie-break the NULL rows by id."""
        await _seed_nullable_parent_items(postgres_session)
        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort("parent_id")),
            search_predicate=None,
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            postgres_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["a", "c", "b1", "b2"]

    @pytest.mark.asyncio
    async def test_descending_nullable_sort_keeps_nulls_last(
        self, postgres_session: AsyncSession
    ) -> None:
        """Keep NULLs last in descending order and tie-break the NULL rows by id."""
        await _seed_nullable_parent_items(postgres_session)
        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort("-parent_id")),
            search_predicate=None,
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            postgres_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["c", "a", "b1", "b2"]

    @pytest.mark.asyncio
    async def test_search_escapes_like_wildcards(
        self, postgres_session: AsyncSession
    ) -> None:
        """Match a literal ``%``/``_`` in the term, not as LIKE wildcards."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        await _create_item(
            session=postgres_session, name="xa_b%y", created_at=base_time
        )
        await _create_item(
            session=postgres_session,
            name="xaXbYy",
            created_at=base_time + timedelta(minutes=1),
        )

        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort(None)),
            search_predicate=build_search_predicate("a_b%", spec.searchable),
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            postgres_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["xa_b%y"]

    @pytest.mark.asyncio
    async def test_search_is_case_insensitive_native_ilike(
        self, postgres_session: AsyncSession
    ) -> None:
        """Match case-insensitively through native PostgreSQL ILIKE."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        await _create_item(
            session=postgres_session, name="FOOBAR", created_at=base_time
        )
        await _create_item(
            session=postgres_session,
            name="other",
            created_at=base_time + timedelta(minutes=1),
        )

        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort(None)),
            search_predicate=build_search_predicate("foo", spec.searchable),
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            postgres_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["FOOBAR"]


@pytest.mark.mysql
class TestListQueryPaginatedMySQL:
    """Cover spec-derived NULLs-last ordering against a real MySQL bind.

    The ascending and descending nullable-sort cases assert the same row-order
    literals as ``TestListQueryPaginatedPostgres``, which is the point: identical
    expectations across dialects show the construct normalises MySQL's ordering to
    the PostgreSQL/SQLite one. The all-NULL and ``select_related`` cases below have
    no PostgreSQL counterpart -- both exercise shapes specific to the prepended
    ``ISNULL`` term.
    """

    @pytest.mark.asyncio
    async def test_ascending_nullable_sort_places_nulls_last(
        self, mysql_session: AsyncSession
    ) -> None:
        """Keep NULLs last in ascending order and tie-break the NULL rows by id."""
        await _seed_nullable_parent_items(mysql_session)
        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort("parent_id")),
            search_predicate=None,
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            mysql_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["a", "c", "b1", "b2"]

    @pytest.mark.asyncio
    async def test_descending_nullable_sort_keeps_nulls_last(
        self, mysql_session: AsyncSession
    ) -> None:
        """Keep NULLs last in descending order and tie-break the NULL rows by id."""
        await _seed_nullable_parent_items(mysql_session)
        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort("-parent_id")),
            search_predicate=None,
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            mysql_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["c", "a", "b1", "b2"]

    @pytest.mark.asyncio
    async def test_all_null_sort_column_falls_back_to_tie_breaker(
        self, mysql_session: AsyncSession
    ) -> None:
        """Keep an all-NULL sort column ordered by the tie-breaker alone, no error."""
        base_time = datetime(2026, 1, 1, tzinfo=UTC)
        for offset, name in enumerate(("first", "second", "third")):
            await _create_item(
                mysql_session,
                name=name,
                created_at=base_time + timedelta(minutes=offset),
            )

        spec = PaginationItemSpecManager.list_query_spec
        list_query = ListQuery(
            order_by=tuple(spec.resolve_sort("-parent_id")),
            search_predicate=None,
        )
        result = await PaginationItemSpecManager.list_query_paginated(
            mysql_session,
            list_query=list_query,
            pagination=Pagination(offset=0, limit=10),
        )

        assert [item.name for item in result.items] == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_select_related_pagination_orders_on_mysql(
        self, mysql_session: AsyncSession
    ) -> None:
        """Apply the two-term MySQL ordering to the id-only pk query and the outer one.

        The ``select_related`` + pagination branch orders a ``SELECT id`` query by a
        different column, so the prepended ``ISNULL`` term has to be valid there too.
        """
        await _seed_nullable_parent_items(mysql_session)

        result = await PaginationItemSpecManager.list(
            mysql_session,
            select_related=[PaginationItem.parent],
            offset=0,
            limit=SELECT_RELATED_PAGE_LIMIT,
        )

        assert [item.name for item in result] == ["a", "b1"]


async def _seed_nullable_parent_items(session: AsyncSession) -> None:
    """Seed items whose nullable ``parent_id`` mixes two parents and two NULLs."""
    parent_one = await _create_parent(session, "parent-1")
    parent_two = await _create_parent(session, "parent-2")
    base_time = datetime(2026, 1, 1, tzinfo=UTC)
    await _create_item(session, name="a", created_at=base_time, parent_id=parent_one.id)
    await _create_item(
        session,
        name="c",
        created_at=base_time + timedelta(minutes=1),
        parent_id=parent_two.id,
    )
    await _create_item(session, name="b1", created_at=base_time + timedelta(minutes=2))
    await _create_item(session, name="b2", created_at=base_time + timedelta(minutes=3))


class TestExists:
    """Cover ``BaseManager.exists`` short-circuit existence checks."""

    @pytest.mark.asyncio
    async def test_exists_false_on_empty_table(self, session: AsyncSession) -> None:
        """Return ``False`` when the table has no rows."""
        assert await UniqueKeyManager.exists(session) is False

    @pytest.mark.asyncio
    async def test_exists_true_with_no_filters(self, session: AsyncSession) -> None:
        """Return ``True`` when any row exists and no filters are applied."""
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="alpha", label="a"),
            filter_include={"key"},
        )
        assert await UniqueKeyManager.exists(session) is True

    @pytest.mark.asyncio
    async def test_exists_with_equal_filters(self, session: AsyncSession) -> None:
        """Apply keyword equal-filters the same way ``count`` does."""
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="alpha", label="a"),
            filter_include={"key"},
        )
        assert await UniqueKeyManager.exists(session, key="alpha") is True
        assert await UniqueKeyManager.exists(session, key="missing") is False

    @pytest.mark.asyncio
    async def test_exists_with_whereclause(self, session: AsyncSession) -> None:
        """Apply a positional ``whereclause`` expression."""
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="alpha", label="keep"),
            filter_include={"key"},
        )
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="beta", label="drop"),
            filter_include={"key"},
        )
        assert (
            await UniqueKeyManager.exists(session, col(UniqueKeyModel.label) == "keep")
            is True
        )
        assert (
            await UniqueKeyManager.exists(session, col(UniqueKeyModel.label) == "gone")
            is False
        )


class TestDMLWhereGuards:
    """Test the guards ``update_where`` and ``delete_where`` apply before running."""

    @pytest.mark.asyncio
    async def test_update_where_rejects_no_filter(self, session: AsyncSession) -> None:
        """Refuse an unbounded UPDATE."""
        with pytest.raises(ValueError, match="at least one filter"):
            await UniqueKeyManager.update_where(session, values={"label": "x"})

    @pytest.mark.asyncio
    async def test_delete_where_rejects_no_filter(self, session: AsyncSession) -> None:
        """Refuse an unbounded DELETE."""
        with pytest.raises(ValueError, match="at least one filter"):
            await UniqueKeyManager.delete_where(session)

    @pytest.mark.asyncio
    async def test_update_where_rejects_empty_returning(
        self, session: AsyncSession
    ) -> None:
        """Refuse a ``returning`` that names no column.

        The overloads promise a list of rows for any non-``bool`` ``returning``, so
        an empty one would return a ``CursorResult`` where a list was declared.
        """
        with pytest.raises(ValueError, match="returning must name at least one"):
            await UniqueKeyManager.update_where(
                session, values={"label": "x"}, returning=[], key="alpha"
            )

    @pytest.mark.asyncio
    async def test_delete_where_rejects_empty_returning(
        self, session: AsyncSession
    ) -> None:
        """Refuse a ``returning`` that names no column, on the DELETE arm too."""
        with pytest.raises(ValueError, match="returning must name at least one"):
            await UniqueKeyManager.delete_where(session, returning=(), key="alpha")

    @pytest.mark.asyncio
    async def test_update_where_rejects_an_empty_generator_returning(
        self, session: AsyncSession
    ) -> None:
        """Refuse an empty one-shot ``returning`` the same as an empty sequence.

        ``Iterable[str]`` admits a generator, which is truthy while empty, so a
        guard reading its truthiness alone would pass it through to the row read
        and raise ``TypeError`` from ``len()`` instead.
        """
        with pytest.raises(ValueError, match="returning must name at least one"):
            await UniqueKeyManager.update_where(
                session,
                values={"label": "x"},
                returning=(column for column in ()),
                key="alpha",
            )

    @pytest.mark.asyncio
    async def test_update_where_accepts_a_generator_returning(
        self, session: AsyncSession
    ) -> None:
        """Honor a one-shot ``returning``, which is consumed more than once below."""
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="alpha", label="before"),
            filter_include={"key"},
        )
        returned = await UniqueKeyManager.update_where(
            session,
            values={"label": "after"},
            returning=(column for column in ["label"]),
            key="alpha",
        )
        assert returned == ["after"]

    @pytest.mark.asyncio
    async def test_update_where_returns_named_columns(
        self, session: AsyncSession
    ) -> None:
        """Honor a ``returning`` that does name a column."""
        await UniqueKeyManager.get_or_create(
            session,
            UniqueKeyModel(key="alpha", label="before"),
            filter_include={"key"},
        )
        returned = await UniqueKeyManager.update_where(
            session, values={"label": "after"}, returning=["label"], key="alpha"
        )
        assert returned == ["after"]

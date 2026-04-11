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

from datetime import datetime, timedelta, UTC

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import col, Relationship, SQLModel
from sqlmodel import Field as SQLField
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from app.core.db import BaseSQLModel
from app.core.db.crud import (
    BaseSQLModelManager,
    DEFAULT_PAGINATION_LIMIT,
)
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.models import PaginatedResponse
from app.core.utils import json_serializer

MATCHING_ITEM_TOTAL = 3
SELECT_RELATED_PAGE_LIMIT = 2
INVALID_PAGINATION_VALUE = -1
UNPAGINATED_ITEM_TOTAL = 55


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
    """Manager for test pagination items with explicit ordering."""

    Model = PaginationItem
    ordering = [col(PaginationItem.name)]


@pytest_asyncio.fixture(name="session")
async def session_fixture() -> AsyncSession:
    """Create an isolated async database session for CRUD pagination tests."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    async_session_maker = get_async_session_maker_from_engine(engine)
    async with async_session_maker() as session:
        yield session


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
    async def test_list_limit_zero_returns_empty_list(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert limit zero returns no records."""
        await _create_item(
            session,
            name="item-0",
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )

        result = await PaginationItemManager.list(session, limit=0)

        assert result == []

    @pytest.mark.asyncio
    async def test_list_negative_offset_raises_value_error(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert negative offsets are rejected."""
        with pytest.raises(
            ValueError, match="offset must be greater than or equal to 0"
        ):
            await PaginationItemManager.list(
                session,
                offset=INVALID_PAGINATION_VALUE,
            )

    @pytest.mark.asyncio
    async def test_list_negative_limit_raises_value_error(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert negative limits are rejected."""
        with pytest.raises(
            ValueError, match="limit must be greater than or equal to 0"
        ):
            await PaginationItemManager.list(
                session,
                limit=INVALID_PAGINATION_VALUE,
            )

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
            offset=1,
            limit=1,
        )

        assert isinstance(result, PaginatedResponse)
        assert result.total == MATCHING_ITEM_TOTAL
        assert result.offset == 1
        assert result.limit == 1
        assert [item.name for item in result.items] == ["match-1"]

    @pytest.mark.asyncio
    async def test_list_paginated_negative_offset_raises_value_error(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert paginated responses reject negative offsets."""
        with pytest.raises(
            ValueError, match="offset must be greater than or equal to 0"
        ):
            await PaginationItemManager.list_paginated(
                session,
                offset=INVALID_PAGINATION_VALUE,
            )

    @pytest.mark.asyncio
    async def test_list_paginated_negative_limit_raises_value_error(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert paginated responses reject negative limits."""
        with pytest.raises(
            ValueError, match="limit must be greater than or equal to 0"
        ):
            await PaginationItemManager.list_paginated(
                session,
                limit=INVALID_PAGINATION_VALUE,
            )

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
            limit=SELECT_RELATED_PAGE_LIMIT,
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
            limit=1,
        )

        assert result.total == 1
        assert len(result.items) == 1
        assert result.items[0].name == "parent-1"
        assert len(result.items[0].items) == MATCHING_ITEM_TOTAL

    @pytest.mark.asyncio
    async def test_explicit_ordering_takes_precedence_over_created_at_fallback(
        self,
        session: AsyncSession,
    ) -> None:
        """Assert managers with explicit ordering ignore the fallback ordering."""
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

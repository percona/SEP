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

"""Tests for SnippetManager CRUD operations."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.pagination import Pagination
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.list_query import (
    SNIPPET_SORT_KEYS,
    SnippetApprovalFilter,
    SnippetListQuery,
    SnippetSortDirection,
)
from app.sep.snippets.models import Snippet


async def _seed_snippet(
    session,
    filename: str,
    *,
    title: str | None = None,
    description: str | None = None,
    service_type: str | None = None,
    approved: bool = False,
) -> Snippet:
    """Persist a Snippet row with the given meta and approval state."""
    meta: dict[str, str] = {}
    if title is not None:
        meta["title"] = title
    if description is not None:
        meta["description"] = description
    if service_type is not None:
        meta["service_type"] = service_type
    snippet = Snippet(filename=filename, size=10, md5_digest="a" * 32, meta=meta)
    if approved:
        snippet.approve("Seeded as approved", "seed-user")
    return await SnippetManager.create(session, snippet)


class TestSnippetManagerGetOrCreate:
    """Test the get_or_create method override."""

    @pytest.mark.asyncio
    async def test_creates_new_snippet_and_calls_update_meta(self, session):
        """Verify new snippet is created and update_meta is called."""
        snippet = Snippet(filename="new.sh", size=50, md5_digest="c" * 32)

        with patch.object(
            Snippet, "update_meta", new_callable=AsyncMock
        ) as mock_update_meta:
            result, created = await SnippetManager.get_or_create(
                session, snippet, filter_include={"filename"}
            )

        assert created is True
        assert result.filename == "new.sh"
        assert result.md5_digest == "c" * 32
        mock_update_meta.assert_awaited_once()

        persisted = await SnippetManager.list(session, filename="new.sh")
        assert len(persisted) == 1
        assert persisted[0].md5_digest == "c" * 32

    @pytest.mark.asyncio
    async def test_returns_existing_snippet(self, session):
        """Verify existing snippet is returned without creating a duplicate."""
        existing = await SnippetManager.create(
            session,
            Snippet(filename="existing.sh", size=100, md5_digest="d" * 32),
        )

        new_snippet = Snippet(filename="existing.sh", size=200, md5_digest="e" * 32)

        with patch.object(
            Snippet, "update_meta", new_callable=AsyncMock
        ) as mock_update_meta:
            result, created = await SnippetManager.get_or_create(
                session, new_snippet, filter_include={"filename"}
            )

        assert created is False
        assert result.id == existing.id
        mock_update_meta.assert_not_awaited()

        persisted = await SnippetManager.list(session, filename="existing.sh")
        assert len(persisted) == 1
        assert persisted[0].md5_digest == "d" * 32


@pytest.mark.asyncio
class TestSnippetManagerListQueryPage:
    """Test server-side search/filter/sort in ``SnippetManager.list_query_page``."""

    async def test_search_matches_filename_title_and_description(self, session):
        """Match filename, meta title, and meta description case-insensitively."""
        await _seed_snippet(session, "mysql-slow.sh", title="Unrelated")
        await _seed_snippet(session, "other.sh", title="MySQL Report")
        await _seed_snippet(session, "third.sh", description="dumps the MYSQL log")
        await _seed_snippet(session, "skip.sh", title="Postgres", description="pg only")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(search="mysql"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == len(page.items)
        assert {s.filename for s in page.items} == {
            "mysql-slow.sh",
            "other.sh",
            "third.sh",
        }

    async def test_search_treats_like_wildcards_as_literals(self, session):
        """Treat a ``%`` in the search term as a literal, not a wildcard."""
        await _seed_snippet(session, "literal.sh", title="100% done")
        await _seed_snippet(session, "decoy.sh", title="nothing here")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(search="100%"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"literal.sh"}

    async def test_blank_search_applies_no_predicate(self, session):
        """Ignore a whitespace-only search term."""
        await _seed_snippet(session, "a.sh")
        await _seed_snippet(session, "b.sh")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(search="   "),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == len(page.items)

    async def test_approval_filter_narrows_to_approved(self, session):
        """Keep only snippets with an approval timestamp under the approved filter."""
        await _seed_snippet(session, "approved.sh", approved=True)
        await _seed_snippet(session, "pending.sh", approved=False)

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(approval=SnippetApprovalFilter.APPROVED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["approved.sh"]

    async def test_approval_filter_narrows_to_not_approved(self, session):
        """Keep only snippets without an approval timestamp under the not-approved filter."""
        await _seed_snippet(session, "approved.sh", approved=True)
        await _seed_snippet(session, "pending.sh", approved=False)

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(approval=SnippetApprovalFilter.NOT_APPROVED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["pending.sh"]

    async def test_service_type_filter_matches_value(self, session):
        """Match the ``meta.service_type`` value with the service-type filter."""
        await _seed_snippet(session, "mongo.sh", service_type="mongodb")
        await _seed_snippet(session, "mysql.sh", service_type="mysql")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type="mongodb"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["mongo.sh"]

    async def test_service_type_equality_matches_trimmed_value(self, session):
        """Match the service-type filter against the trimmed stored value."""
        await _seed_snippet(session, "padded.sh", service_type="  mysql  ")
        await _seed_snippet(session, "mongo.sh", service_type="mongodb")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type="mysql"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["padded.sh"]

    async def test_uncategorized_selects_absent_and_blank_service_types(self, session):
        """Select snippets whose service type is absent or blank when uncategorized."""
        await _seed_snippet(session, "typed.sh", service_type="mysql")
        await _seed_snippet(session, "absent.sh")
        await _seed_snippet(session, "empty.sh", service_type="")
        await _seed_snippet(session, "blank.sh", service_type="   ")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {
            "absent.sh",
            "empty.sh",
            "blank.sh",
        }

    async def test_uncategorized_does_not_match_literal_reserved_value(self, session):
        """Treat a literal ``__uncategorized__`` service type as a real value."""
        await _seed_snippet(session, "literal.sh", service_type="__uncategorized__")
        await _seed_snippet(session, "absent.sh")

        uncategorized_page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )
        equality_page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type="__uncategorized__"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in uncategorized_page.items] == ["absent.sh"]
        assert [s.filename for s in equality_page.items] == ["literal.sh"]

    async def test_uncategorized_takes_precedence_over_service_type(self, session):
        """Prefer the uncategorized flag over a supplied service-type value."""
        await _seed_snippet(session, "typed.sh", service_type="mysql")
        await _seed_snippet(session, "absent.sh")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type="mysql", uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["absent.sh"]

    async def test_filtered_total_matches_the_filtered_result_set(self, session):
        """Reflect the filtered query in the paginated total, not the whole table."""
        mysql_count = 5
        page_limit = 2
        for index in range(mysql_count):
            await _seed_snippet(session, f"mysql-{index}.sh", service_type="mysql")
        await _seed_snippet(session, "mongo.sh", service_type="mongodb")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type="mysql"),
            pagination=Pagination(offset=0, limit=page_limit),
        )

        assert page.total == mysql_count
        assert len(page.items) == page_limit

    async def test_ordering_is_deterministic_across_page_boundaries(self, session):
        """Break a tie on the sort key by filename so pages never overlap or drop."""
        for name in ("d.sh", "b.sh", "a.sh", "c.sh"):
            await _seed_snippet(session, name, service_type="mysql")

        query = SnippetListQuery(
            sort_key="service_type", sort_direction=SnippetSortDirection.ASC
        )
        first = await SnippetManager.list_query_page(
            session, list_query=query, pagination=Pagination(offset=0, limit=2)
        )
        second = await SnippetManager.list_query_page(
            session, list_query=query, pagination=Pagination(offset=2, limit=2)
        )

        assert [s.filename for s in first.items] == ["a.sh", "b.sh"]
        assert [s.filename for s in second.items] == ["c.sh", "d.sh"]

    async def test_sort_by_meta_title_ascending(self, session):
        """Order by the ``meta.title`` JSON value for the title sort key."""
        await _seed_snippet(session, "one.sh", title="Charlie")
        await _seed_snippet(session, "two.sh", title="Alpha")
        await _seed_snippet(session, "three.sh", title="Bravo")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(
                sort_key="title", sort_direction=SnippetSortDirection.ASC
            ),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.title for s in page.items] == ["Alpha", "Bravo", "Charlie"]

    async def test_every_allowlisted_sort_key_resolves(self, session):
        """Resolve every public sort key to a runnable ordered query."""
        await _seed_snippet(session, "b.sh", title="B", service_type="mysql")
        await _seed_snippet(session, "a.sh", title="A", service_type="mongodb")

        for sort_key in SNIPPET_SORT_KEYS:
            page = await SnippetManager.list_query_page(
                session,
                list_query=SnippetListQuery(sort_key=sort_key),
                pagination=Pagination(offset=0, limit=50),
            )
            assert page.total == len(page.items)

    async def test_empty_table_returns_zero_total(self, session):
        """Yield an empty page with a zero total for an empty table."""
        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == 0
        assert page.items == []


@pytest.mark.asyncio
class TestSnippetManagerListServiceTypes:
    """Test the whole-dataset service-type facet in ``list_service_types``."""

    async def test_returns_sorted_distinct_trimmed_values(self, session):
        """Return the sorted distinct trimmed service types across the table."""
        await _seed_snippet(session, "a.sh", service_type="mysql")
        await _seed_snippet(session, "b.sh", service_type="mongodb")
        await _seed_snippet(session, "c.sh", service_type="  mysql  ")
        await _seed_snippet(session, "d.sh", service_type="postgresql")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == ["mongodb", "mysql", "postgresql"]
        assert has_uncategorized is False

    async def test_flags_uncategorized_for_absent_or_blank_values(self, session):
        """Flag uncategorized when any snippet has an absent or blank service type."""
        await _seed_snippet(session, "typed.sh", service_type="mysql")
        await _seed_snippet(session, "absent.sh")
        await _seed_snippet(session, "blank.sh", service_type="   ")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == ["mysql"]
        assert has_uncategorized is True

    async def test_empty_table_returns_no_types(self, session):
        """Return no service types and no uncategorized flag for an empty table."""
        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == []
        assert has_uncategorized is False

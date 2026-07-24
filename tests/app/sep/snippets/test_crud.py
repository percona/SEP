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
    SERVICE_TYPE_UNCATEGORIZED,
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
        """Search matches filename, meta title, and meta description, case-insensitively."""
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
        """A ``%`` in the search term matches literally, not as a wildcard."""
        await _seed_snippet(session, "literal.sh", title="100% done")
        await _seed_snippet(session, "decoy.sh", title="nothing here")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(search="100%"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"literal.sh"}

    async def test_blank_search_applies_no_predicate(self, session):
        """A whitespace-only search term is ignored."""
        await _seed_snippet(session, "a.sh")
        await _seed_snippet(session, "b.sh")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(search="   "),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == len(page.items)

    async def test_approval_filter_narrows_to_approved(self, session):
        """The approved filter keeps only snippets with an approval timestamp."""
        await _seed_snippet(session, "approved.sh", approved=True)
        await _seed_snippet(session, "pending.sh", approved=False)

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(approval=SnippetApprovalFilter.APPROVED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["approved.sh"]

    async def test_approval_filter_narrows_to_not_approved(self, session):
        """The not-approved filter keeps only snippets without an approval timestamp."""
        await _seed_snippet(session, "approved.sh", approved=True)
        await _seed_snippet(session, "pending.sh", approved=False)

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(approval=SnippetApprovalFilter.NOT_APPROVED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["pending.sh"]

    async def test_service_type_filter_matches_value(self, session):
        """The service-type filter matches the ``meta.service_type`` value."""
        await _seed_snippet(session, "mongo.sh", service_type="mongodb")
        await _seed_snippet(session, "mysql.sh", service_type="mysql")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type="mongodb"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["mongo.sh"]

    async def test_service_type_uncategorized_selects_snippets_without_a_type(
        self, session
    ):
        """The uncategorized sentinel selects snippets whose service type is absent."""
        await _seed_snippet(session, "typed.sh", service_type="mysql")
        await _seed_snippet(session, "untyped.sh")

        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(service_type=SERVICE_TYPE_UNCATEGORIZED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["untyped.sh"]

    async def test_filtered_total_matches_the_filtered_result_set(self, session):
        """The paginated total reflects the filtered query, not the whole table."""
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
        """A tie on the sort key is broken by filename, so pages never overlap or drop."""
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
        """The title sort key orders by the ``meta.title`` JSON value."""
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
        """Every public sort key produces a runnable ordered query."""
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
        """An empty table yields an empty page with a zero total."""
        page = await SnippetManager.list_query_page(
            session,
            list_query=SnippetListQuery(),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == 0
        assert page.items == []

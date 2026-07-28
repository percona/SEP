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

"""Tests for SnippetManager CRUD and its Core-backed list-query spec."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import col

from app.core.db.list_query import build_search_predicate, ListQuery
from app.core.pagination import Pagination
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.list_query import SnippetApprovalFilter, SnippetListQuery
from app.sep.snippets.models import Snippet

_SPEC = SnippetManager.list_query_spec


def _list_query(sort: str | None = None, search: str | None = None) -> ListQuery:
    """Build a :class:`ListQuery` from the snippet spec, as the request dep would.

    :param sort: The raw ``sort`` value (``-`` prefix for descending), or ``None``
        for the spec default.
    :param search: The raw search term, or ``None`` for no search.
    :return: The resolved list query.
    """
    return ListQuery(
        order_by=tuple(_SPEC.resolve_sort(sort)),
        search_predicate=build_search_predicate(search, _SPEC.searchable),
    )


async def _page(session, sort=None, search=None, offset=0, limit=50):
    return await SnippetManager.list_query_paginated(
        session,
        list_query=_list_query(sort=sort, search=search),
        pagination=Pagination(offset=offset, limit=limit),
    )


def _snippet_query(
    sort: str | None = None,
    search: str | None = None,
    approval: SnippetApprovalFilter = SnippetApprovalFilter.ALL,
    service_type: str | None = None,
    *,
    uncategorized: bool = False,
) -> SnippetListQuery:
    """Build the composed snippets list query, as ``get_snippet_list_query`` would.

    :param sort: The raw ``sort`` value, or ``None`` for the spec default.
    :param search: The raw search term, or ``None`` for no search.
    :param approval: The approval-status filter.
    :param service_type: The service-type equality filter, or ``None`` for none.
    :param uncategorized: Whether to keep only snippets with no service type.
    :return: The composed list query.
    """
    return SnippetListQuery(
        core=_list_query(sort=sort, search=search),
        approval=approval,
        service_type=service_type,
        uncategorized=uncategorized,
    )


async def _filtered_page(session, offset=0, limit=50, **query):
    return await SnippetManager.snippet_list_page(
        session,
        list_query=_snippet_query(**query),
        pagination=Pagination(offset=offset, limit=limit),
    )


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


class TestSnippetListQuerySpec:
    """Assert the spec's shape: allowlist keys, default, tie-breaker, searchable."""

    def test_allowlist_keys(self):
        """Expose exactly the five public sort keys."""
        assert set(_SPEC.sortable) == {
            "created_at",
            "filename",
            "approved_at",
            "title",
            "service_type",
        }

    def test_default_sort_reproduces_the_approved_first_ordering(self):
        """Default to approved-first, matching the legacy ``ordering`` attribute."""
        assert _SPEC.default_sort == "-approved_at"

    def test_tie_breaker_is_the_primary_key(self):
        """Break ties on the unique ``id`` so pagination cannot repeat or drop rows."""
        assert _SPEC.tie_breaker is col(Snippet.id)

    def test_derived_ordering_matches_the_spec_default(self):
        """Derive the manager default ordering from the spec, not from ``ordering``."""
        assert [str(clause) for clause in SnippetManager._get_ordering()] == [
            "snippet.approved_at DESC NULLS LAST",
            "snippet.id ASC",
        ]

    def test_search_is_enabled(self):
        """Enable search (filename, title, description are searchable)."""
        assert _SPEC.search_enabled is True


@pytest.mark.asyncio
class TestSnippetManagerListQueryPaginated:
    """Test server-side search and sort through the Core list-query primitives."""

    async def test_search_matches_filename_title_and_description(
        self, session, seed_snippet
    ):
        """Match filename, meta title, and meta description case-insensitively."""
        await seed_snippet(session, "mysql-slow.sh", title="Unrelated")
        await seed_snippet(session, "other.sh", title="MySQL Report")
        await seed_snippet(session, "third.sh", description="dumps the MYSQL log")
        await seed_snippet(session, "skip.sh", title="Postgres", description="pg only")

        page = await _page(session, search="mysql")

        assert page.total == len(page.items)
        assert {s.filename for s in page.items} == {
            "mysql-slow.sh",
            "other.sh",
            "third.sh",
        }

    async def test_search_treats_percent_wildcard_as_literal(
        self, session, seed_snippet
    ):
        """Treat a ``%`` in the search term as a literal, not a wildcard."""
        await seed_snippet(session, "literal.sh", title="100% done")
        await seed_snippet(session, "decoy.sh", title="nothing here")

        page = await _page(session, search="100%")

        assert {s.filename for s in page.items} == {"literal.sh"}

    async def test_search_treats_underscore_wildcard_as_literal(
        self, session, seed_snippet
    ):
        """Treat ``_`` in the search term as a literal, not a single-char wildcard."""
        await seed_snippet(session, "a_b.sh", title="a_b match")
        await seed_snippet(session, "axb.sh", title="axb decoy")

        page = await _page(session, search="a_b")

        assert {s.filename for s in page.items} == {"a_b.sh"}

    async def test_search_treats_backslash_as_literal(self, session, seed_snippet):
        r"""Treat a backslash in the search term as a literal, not an escape char."""
        await seed_snippet(session, "match.sh", title=r"path\to\file")
        await seed_snippet(session, "decoy.sh", title="pathtofile")

        page = await _page(session, search=r"path\to")

        assert {s.filename for s in page.items} == {"match.sh"}

    async def test_search_matches_unicode_terms(self, session, seed_snippet):
        """Match a multibyte unicode search term case-insensitively."""
        await seed_snippet(session, "cafe.sh", title="Café Menu")
        await seed_snippet(session, "plain.sh", title="Diner")

        page = await _page(session, search="café")

        assert {s.filename for s in page.items} == {"cafe.sh"}

    async def test_blank_search_applies_no_predicate(self, session, seed_snippet):
        """Ignore a whitespace-only search term."""
        names = ("a.sh", "b.sh")
        for name in names:
            await seed_snippet(session, name)

        page = await _page(session, search="   ")

        assert page.total == len(page.items) == len(names)

    async def test_filtered_total_matches_the_filtered_result_set(
        self, session, seed_snippet
    ):
        """Reflect the filtered query in the paginated total, not the whole table."""
        mysql_count = 5
        page_limit = 2
        for index in range(mysql_count):
            await seed_snippet(session, f"mysql-{index}.sh", title="mysql tool")
        await seed_snippet(session, "mongo.sh", title="mongo tool")

        page = await _page(session, search="mysql", limit=page_limit)

        assert page.total == mysql_count
        assert len(page.items) == page_limit

    async def test_default_sort_breaks_approved_at_ties_by_id(
        self, session, seed_snippet
    ):
        """Fall back to the ``id`` tie-breaker when ``approved_at`` values tie.

        The default sort is ``approved_at`` descending, and unapproved rows all share
        a ``NULL``, so the unique ``id`` tie-breaker (ascending) fixes the order
        deterministically instead of leaving it undefined.
        """
        for name in ("b.sh", "a.sh", "c.sh"):
            await seed_snippet(session, name)

        page = await _page(session)

        assert [s.filename for s in page.items] == ["b.sh", "a.sh", "c.sh"]

    async def test_sort_by_meta_title_ascending(self, session, seed_snippet):
        """Order by the ``meta.title`` JSON value for the ascending title sort key."""
        await seed_snippet(session, "one.sh", title="Charlie")
        await seed_snippet(session, "two.sh", title="Alpha")
        await seed_snippet(session, "three.sh", title="Bravo")

        page = await _page(session, sort="title")

        assert [s.title for s in page.items] == ["Alpha", "Bravo", "Charlie"]

    async def test_sort_by_meta_title_descending(self, session, seed_snippet):
        """Order by the ``meta.title`` JSON value for the descending title sort key."""
        await seed_snippet(session, "one.sh", title="Charlie")
        await seed_snippet(session, "two.sh", title="Alpha")
        await seed_snippet(session, "three.sh", title="Bravo")

        page = await _page(session, sort="-title")

        assert [s.title for s in page.items] == ["Charlie", "Bravo", "Alpha"]

    async def test_sort_by_filename_ascending_and_descending(
        self, session, seed_snippet
    ):
        """Order by the filename column directly in both directions."""
        for name in ("b.sh", "a.sh", "c.sh"):
            await seed_snippet(session, name)

        ascending = await _page(session, sort="filename")
        descending = await _page(session, sort="-filename")

        assert [s.filename for s in ascending.items] == ["a.sh", "b.sh", "c.sh"]
        assert [s.filename for s in descending.items] == ["c.sh", "b.sh", "a.sh"]

    async def test_sort_by_meta_title_places_missing_titles_last(
        self, session, seed_snippet
    ):
        """Pin rows lacking the sorted meta key last in both sort directions.

        The primary sort expression is NULL for a snippet with no ``meta.title``;
        without an explicit NULL placement SQLite and PostgreSQL disagree on where
        those rows land. They must sort last ascending and descending alike, then
        break ties by filename.
        """
        await seed_snippet(session, "alpha.sh", title="Alpha")
        await seed_snippet(session, "bravo.sh", title="Bravo")
        await seed_snippet(session, "no-title-1.sh")
        await seed_snippet(session, "no-title-2.sh")

        ascending = await _page(session, sort="title")
        descending = await _page(session, sort="-title")

        assert [s.filename for s in ascending.items] == [
            "alpha.sh",
            "bravo.sh",
            "no-title-1.sh",
            "no-title-2.sh",
        ]
        assert [s.filename for s in descending.items] == [
            "bravo.sh",
            "alpha.sh",
            "no-title-1.sh",
            "no-title-2.sh",
        ]

    async def test_ordering_is_deterministic_across_page_boundaries(
        self, session, seed_snippet
    ):
        """Break a tie on the sort key by ``id`` so pages never overlap or drop."""
        for name in ("d.sh", "b.sh", "a.sh", "c.sh"):
            await seed_snippet(session, name, service_type="mysql")

        first = await _page(session, sort="service_type", offset=0, limit=2)
        second = await _page(session, sort="service_type", offset=2, limit=2)

        assert [s.filename for s in first.items] == ["d.sh", "b.sh"]
        assert [s.filename for s in second.items] == ["a.sh", "c.sh"]

    @pytest.mark.parametrize("sort_key", list(_SPEC.sortable))
    async def test_allowlisted_sort_key_resolves(self, session, seed_snippet, sort_key):
        """Resolve every public sort key to a runnable ordered query."""
        seeded = 2
        await seed_snippet(session, "b.sh", title="B", service_type="mysql")
        await seed_snippet(session, "a.sh", title="A", service_type="mongodb")

        page = await _page(session, sort=sort_key)

        assert page.total == len(page.items) == seeded

    async def test_empty_table_returns_zero_total(self, session):
        """Yield an empty page with a zero total for an empty table."""
        page = await _page(session)

        assert page.total == 0
        assert page.items == []


@pytest.mark.asyncio
class TestSnippetManagerListQueryOnPostgres:
    """Exercise the dialect-specific JSON extract and NULL ordering on PostgreSQL.

    SQLite is not a substitute for PostgreSQL's ``->>`` JSON extract and NULL
    ordering, so these run against a real ``postgres_session`` (auto-skipped when
    ``SEP_TEST_POSTGRES_DSN`` is unset).
    """

    async def test_search_matches_json_title_and_description(
        self, postgres_session, seed_snippet
    ):
        """Search the ``meta`` JSON title/description via the ``->>`` extract."""
        await seed_snippet(postgres_session, "other.sh", title="MySQL Report")
        await seed_snippet(postgres_session, "third.sh", description="the MYSQL log")
        await seed_snippet(postgres_session, "skip.sh", title="Postgres")

        page = await _page(postgres_session, search="mysql")

        assert {s.filename for s in page.items} == {"other.sh", "third.sh"}

    async def test_sort_by_meta_title_orders_by_json_value(
        self, postgres_session, seed_snippet
    ):
        """Order by the ``meta.title`` JSON value ascending on PostgreSQL."""
        await seed_snippet(postgres_session, "one.sh", title="Charlie")
        await seed_snippet(postgres_session, "two.sh", title="Alpha")
        await seed_snippet(postgres_session, "three.sh", title="Bravo")

        page = await _page(postgres_session, sort="title")

        assert [s.title for s in page.items] == ["Alpha", "Bravo", "Charlie"]

    async def test_sort_by_meta_title_places_missing_titles_last(
        self, postgres_session, seed_snippet
    ):
        """Pin rows lacking ``meta.title`` last in both directions on PostgreSQL.

        PostgreSQL defaults NULLs last on ASC and first on DESC, so only the
        explicit ``NULLS LAST`` keeps the untitled rows last in both directions --
        matching the SQLite path.
        """
        await seed_snippet(postgres_session, "alpha.sh", title="Alpha")
        await seed_snippet(postgres_session, "bravo.sh", title="Bravo")
        await seed_snippet(postgres_session, "no-title-1.sh")
        await seed_snippet(postgres_session, "no-title-2.sh")

        ascending = await _page(postgres_session, sort="title")
        descending = await _page(postgres_session, sort="-title")

        assert [s.filename for s in ascending.items] == [
            "alpha.sh",
            "bravo.sh",
            "no-title-1.sh",
            "no-title-2.sh",
        ]
        assert [s.filename for s in descending.items] == [
            "bravo.sh",
            "alpha.sh",
            "no-title-1.sh",
            "no-title-2.sh",
        ]

    async def test_ordering_is_deterministic_across_page_boundaries(
        self, postgres_session, seed_snippet
    ):
        """Break a sort-key tie by filename so pages never overlap on PostgreSQL."""
        for name in ("d.sh", "b.sh", "a.sh", "c.sh"):
            await seed_snippet(postgres_session, name, service_type="mysql")

        first = await _page(postgres_session, sort="service_type", offset=0, limit=2)
        second = await _page(postgres_session, sort="service_type", offset=2, limit=2)

        assert [s.filename for s in first.items] == ["a.sh", "b.sh"]
        assert [s.filename for s in second.items] == ["c.sh", "d.sh"]


@pytest.mark.asyncio
class TestSnippetListPageFilters:
    """Test the snippets filters composing with the Core sort/search predicates."""

    async def test_approval_filter_narrows_to_approved(self, session, seed_snippet):
        """Keep only snippets with an approval timestamp under the approved filter."""
        await seed_snippet(session, "approved.sh", approved=True)
        await seed_snippet(session, "pending.sh", approved=False)

        page = await _filtered_page(session, approval=SnippetApprovalFilter.APPROVED)

        assert [s.filename for s in page.items] == ["approved.sh"]

    async def test_approval_filter_narrows_to_not_approved(self, session, seed_snippet):
        """Keep only snippets without an approval timestamp under not-approved."""
        await seed_snippet(session, "approved.sh", approved=True)
        await seed_snippet(session, "pending.sh", approved=False)

        page = await _filtered_page(
            session, approval=SnippetApprovalFilter.NOT_APPROVED
        )

        assert [s.filename for s in page.items] == ["pending.sh"]

    async def test_service_type_filter_matches_value(self, session, seed_snippet):
        """Match the ``meta.service_type`` value with the service-type filter."""
        await seed_snippet(session, "mongo.sh", service_type="mongodb")
        await seed_snippet(session, "mysql.sh", service_type="mysql")

        page = await _filtered_page(session, service_type="mongodb")

        assert [s.filename for s in page.items] == ["mongo.sh"]

    async def test_service_type_equality_matches_trimmed_value(
        self, session, seed_snippet
    ):
        """Match the service-type filter against the trimmed stored value."""
        await seed_snippet(session, "padded.sh", service_type="  mysql  ")
        await seed_snippet(session, "mongo.sh", service_type="mongodb")

        page = await _filtered_page(session, service_type="mysql")

        assert [s.filename for s in page.items] == ["padded.sh"]

    async def test_uncategorized_selects_absent_and_blank_service_types(
        self, session, seed_snippet
    ):
        """Select snippets whose service type is absent or blank when uncategorized."""
        await seed_snippet(session, "typed.sh", service_type="mysql")
        await seed_snippet(session, "absent.sh")
        await seed_snippet(session, "empty.sh", service_type="")
        await seed_snippet(session, "blank.sh", service_type="   ")

        page = await _filtered_page(session, uncategorized=True)

        assert {s.filename for s in page.items} == {
            "absent.sh",
            "empty.sh",
            "blank.sh",
        }

    async def test_uncategorized_does_not_match_literal_reserved_value(
        self, session, seed_snippet
    ):
        """Treat a literal ``__uncategorized__`` service type as a real value."""
        await seed_snippet(session, "literal.sh", service_type="__uncategorized__")
        await seed_snippet(session, "absent.sh")

        uncategorized = await _filtered_page(session, uncategorized=True)
        equality = await _filtered_page(session, service_type="__uncategorized__")

        assert [s.filename for s in uncategorized.items] == ["absent.sh"]
        assert [s.filename for s in equality.items] == ["literal.sh"]

    async def test_uncategorized_takes_precedence_over_service_type(
        self, session, seed_snippet
    ):
        """Prefer the uncategorized flag over a supplied service-type value."""
        await seed_snippet(session, "typed.sh", service_type="mysql")
        await seed_snippet(session, "absent.sh")

        page = await _filtered_page(session, service_type="mysql", uncategorized=True)

        assert [s.filename for s in page.items] == ["absent.sh"]

    async def test_empty_service_type_matches_blank_but_not_absent(
        self, session, seed_snippet
    ):
        """Match a blank stored value, not an absent key, for an empty filter value."""
        await seed_snippet(session, "empty.sh", service_type="")
        await seed_snippet(session, "absent.sh")

        page = await _filtered_page(session, service_type="")

        assert [s.filename for s in page.items] == ["empty.sh"]

    async def test_filters_compose_with_search_and_filtered_total(
        self, session, seed_snippet
    ):
        """Intersect the filters with the Core search and report the shared total."""
        matching = 2
        page_limit = 1
        await seed_snippet(
            session, "mysql-slow.sh", service_type="mysql", approved=True
        )
        await seed_snippet(
            session, "mysql-locks.sh", service_type="mysql", approved=True
        )
        await seed_snippet(
            session, "mysql-pending.sh", service_type="mysql", approved=False
        )
        await seed_snippet(session, "mongo-slow.sh", service_type="mongodb")

        page = await _filtered_page(
            session,
            search="mysql",
            approval=SnippetApprovalFilter.APPROVED,
            service_type="mysql",
            limit=page_limit,
        )

        assert page.total == matching
        assert len(page.items) == page_limit

    async def test_filters_compose_with_an_explicit_sort(self, session, seed_snippet):
        """Order the filtered rows by the requested allowlisted sort key."""
        await seed_snippet(session, "b.sh", service_type="mysql", title="Bravo")
        await seed_snippet(session, "a.sh", service_type="mysql", title="Alpha")
        await seed_snippet(session, "z.sh", service_type="mongodb", title="Zulu")

        page = await _filtered_page(session, sort="title", service_type="mysql")

        assert [s.filename for s in page.items] == ["a.sh", "b.sh"]


@pytest.mark.asyncio
class TestSnippetManagerListServiceTypes:
    """Test the whole-dataset service-type facet backing the list filter."""

    async def test_returns_sorted_distinct_trimmed_values(self, session, seed_snippet):
        """Return each distinct trimmed service type once, sorted."""
        await seed_snippet(session, "a.sh", service_type="mysql")
        await seed_snippet(session, "b.sh", service_type="  mysql  ")
        await seed_snippet(session, "c.sh", service_type="mongodb")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == ["mongodb", "mysql"]
        assert has_uncategorized is False

    async def test_flags_uncategorized_for_absent_or_blank_values(
        self, session, seed_snippet
    ):
        """Fold absent and blank service types into the uncategorized flag."""
        await seed_snippet(session, "typed.sh", service_type="mysql")
        await seed_snippet(session, "absent.sh")
        await seed_snippet(session, "blank.sh", service_type="   ")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == ["mysql"]
        assert has_uncategorized is True

    async def test_empty_table_returns_no_types(self, session):
        """Report no service types and no uncategorized rows for an empty table."""
        assert await SnippetManager.list_service_types(session) == ([], False)

    async def test_facet_and_filter_agree_on_a_padded_value(
        self, session, seed_snippet
    ):
        """Offer the trimmed value the equality filter then matches."""
        await seed_snippet(session, "padded.sh", service_type="\tmysql\t")

        service_types, _ = await SnippetManager.list_service_types(session)
        page = await _filtered_page(session, service_type=service_types[0])

        assert [s.filename for s in page.items] == ["padded.sh"]

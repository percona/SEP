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
from sqlalchemy.dialects import mysql
from sqlmodel import col, select

from app.core.pagination import Pagination
from app.core.utils.fields import DatabaseDialect
from app.sep.snippets.crud import SnippetManager
from app.sep.snippets.list_query import (
    SNIPPET_SORT_KEYS,
    SnippetApprovalFilter,
    SnippetListQuery,
    SnippetSortDirection,
    SnippetSortKey,
)
from app.sep.snippets.models import Snippet


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
    """Test server-side search/filter/sort in ``SnippetManager.snippet_list_page``."""

    async def test_search_matches_filename_title_and_description(
        self, session, seed_snippet
    ):
        """Match filename, meta title, and meta description case-insensitively."""
        await seed_snippet(session, "mysql-slow.sh", title="Unrelated")
        await seed_snippet(session, "other.sh", title="MySQL Report")
        await seed_snippet(session, "third.sh", description="dumps the MYSQL log")
        await seed_snippet(session, "skip.sh", title="Postgres", description="pg only")

        page = await SnippetManager.snippet_list_page(
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

    async def test_search_treats_like_wildcards_as_literals(
        self, session, seed_snippet
    ):
        """Treat a ``%`` in the search term as a literal, not a wildcard."""
        await seed_snippet(session, "literal.sh", title="100% done")
        await seed_snippet(session, "decoy.sh", title="nothing here")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(search="100%"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"literal.sh"}

    async def test_blank_search_applies_no_predicate(self, session, seed_snippet):
        """Ignore a whitespace-only search term."""
        await seed_snippet(session, "a.sh")
        await seed_snippet(session, "b.sh")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(search="   "),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == len(page.items)

    async def test_approval_filter_narrows_to_approved(self, session, seed_snippet):
        """Keep only snippets with an approval timestamp under the approved filter."""
        await seed_snippet(session, "approved.sh", approved=True)
        await seed_snippet(session, "pending.sh", approved=False)

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(approval=SnippetApprovalFilter.APPROVED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["approved.sh"]

    async def test_approval_filter_narrows_to_not_approved(self, session, seed_snippet):
        """Keep only snippets without an approval timestamp under the not-approved filter."""
        await seed_snippet(session, "approved.sh", approved=True)
        await seed_snippet(session, "pending.sh", approved=False)

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(approval=SnippetApprovalFilter.NOT_APPROVED),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["pending.sh"]

    async def test_service_type_filter_matches_value(self, session, seed_snippet):
        """Match the ``meta.service_type`` value with the service-type filter."""
        await seed_snippet(session, "mongo.sh", service_type="mongodb")
        await seed_snippet(session, "mysql.sh", service_type="mysql")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type="mongodb"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["mongo.sh"]

    async def test_service_type_equality_matches_trimmed_value(
        self, session, seed_snippet
    ):
        """Match the service-type filter against the trimmed stored value."""
        await seed_snippet(session, "padded.sh", service_type="  mysql  ")
        await seed_snippet(session, "mongo.sh", service_type="mongodb")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type="mysql"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["padded.sh"]

    async def test_uncategorized_selects_absent_and_blank_service_types(
        self, session, seed_snippet
    ):
        """Select snippets whose service type is absent or blank when uncategorized."""
        await seed_snippet(session, "typed.sh", service_type="mysql")
        await seed_snippet(session, "absent.sh")
        await seed_snippet(session, "empty.sh", service_type="")
        await seed_snippet(session, "blank.sh", service_type="   ")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

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

        uncategorized_page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )
        equality_page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type="__uncategorized__"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in uncategorized_page.items] == ["absent.sh"]
        assert [s.filename for s in equality_page.items] == ["literal.sh"]

    async def test_uncategorized_takes_precedence_over_service_type(
        self, session, seed_snippet
    ):
        """Prefer the uncategorized flag over a supplied service-type value."""
        await seed_snippet(session, "typed.sh", service_type="mysql")
        await seed_snippet(session, "absent.sh")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type="mysql", uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["absent.sh"]

    async def test_filtered_total_matches_the_filtered_result_set(
        self, session, seed_snippet
    ):
        """Reflect the filtered query in the paginated total, not the whole table."""
        mysql_count = 5
        page_limit = 2
        for index in range(mysql_count):
            await seed_snippet(session, f"mysql-{index}.sh", service_type="mysql")
        await seed_snippet(session, "mongo.sh", service_type="mongodb")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type="mysql"),
            pagination=Pagination(offset=0, limit=page_limit),
        )

        assert page.total == mysql_count
        assert len(page.items) == page_limit

    async def test_ordering_is_deterministic_across_page_boundaries(
        self, session, seed_snippet
    ):
        """Break a tie on the sort key by filename so pages never overlap or drop."""
        for name in ("d.sh", "b.sh", "a.sh", "c.sh"):
            await seed_snippet(session, name, service_type="mysql")

        query = SnippetListQuery(
            sort_key=SnippetSortKey.SERVICE_TYPE,
            sort_direction=SnippetSortDirection.ASC,
        )
        first = await SnippetManager.snippet_list_page(
            session, list_query=query, pagination=Pagination(offset=0, limit=2)
        )
        second = await SnippetManager.snippet_list_page(
            session, list_query=query, pagination=Pagination(offset=2, limit=2)
        )

        assert [s.filename for s in first.items] == ["a.sh", "b.sh"]
        assert [s.filename for s in second.items] == ["c.sh", "d.sh"]

    async def test_sort_by_meta_title_ascending(self, session, seed_snippet):
        """Order by the ``meta.title`` JSON value for the title sort key."""
        await seed_snippet(session, "one.sh", title="Charlie")
        await seed_snippet(session, "two.sh", title="Alpha")
        await seed_snippet(session, "three.sh", title="Bravo")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.ASC
            ),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.title for s in page.items] == ["Alpha", "Bravo", "Charlie"]

    @pytest.mark.parametrize("sort_key", list(SNIPPET_SORT_KEYS))
    async def test_allowlisted_sort_key_resolves(self, session, seed_snippet, sort_key):
        """Resolve every public sort key to a runnable ordered query."""
        await seed_snippet(session, "b.sh", title="B", service_type="mysql")
        await seed_snippet(session, "a.sh", title="A", service_type="mongodb")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(sort_key=sort_key),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == len(page.items)

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

        ascending = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.ASC
            ),
            pagination=Pagination(offset=0, limit=50),
        )
        descending = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.DESC
            ),
            pagination=Pagination(offset=0, limit=50),
        )

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

    async def test_sort_by_filename_orders_without_redundant_tie_breaker(
        self, session, seed_snippet
    ):
        """Order by the filename column directly for the filename sort key.

        Filename is itself the unique tie-breaker, so it drives the sole ORDER BY
        clause; ascending and descending both run and stay deterministic.
        """
        for name in ("b.sh", "a.sh", "c.sh"):
            await seed_snippet(session, name)

        ascending = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.FILENAME,
                sort_direction=SnippetSortDirection.ASC,
            ),
            pagination=Pagination(offset=0, limit=50),
        )
        descending = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.FILENAME,
                sort_direction=SnippetSortDirection.DESC,
            ),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in ascending.items] == ["a.sh", "b.sh", "c.sh"]
        assert [s.filename for s in descending.items] == ["c.sh", "b.sh", "a.sh"]

    async def test_empty_service_type_matches_blank_but_not_absent(
        self, session, seed_snippet
    ):
        """Match stored empty/blank types with ``service_type=""`` but not absent ones.

        An explicit empty-string filter takes the equality branch (``TRIM == ''``),
        so it selects stored empty/blank values yet excludes absent (JSON NULL)
        rows -- a strictly narrower set than the uncategorized flag, which also
        keeps the absent row.
        """
        await seed_snippet(session, "absent.sh")
        await seed_snippet(session, "empty.sh", service_type="")
        await seed_snippet(session, "blank.sh", service_type="   ")
        await seed_snippet(session, "typed.sh", service_type="mysql")

        equality_page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type=""),
            pagination=Pagination(offset=0, limit=50),
        )
        uncategorized_page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in equality_page.items} == {"empty.sh", "blank.sh"}
        assert {s.filename for s in uncategorized_page.items} == {
            "absent.sh",
            "empty.sh",
            "blank.sh",
        }

    async def test_search_treats_underscore_wildcard_as_literal(
        self, session, seed_snippet
    ):
        """Treat ``_`` in the search term as a literal, not a single-char wildcard."""
        await seed_snippet(session, "a_b.sh", title="a_b match")
        await seed_snippet(session, "axb.sh", title="axb decoy")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(search="a_b"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"a_b.sh"}

    async def test_search_treats_backslash_as_literal(self, session, seed_snippet):
        r"""Treat a backslash in the search term as a literal, not an escape char."""
        await seed_snippet(session, "match.sh", title=r"path\to\file")
        await seed_snippet(session, "decoy.sh", title="pathtofile")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(search=r"path\to"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"match.sh"}

    async def test_search_matches_unicode_terms(self, session, seed_snippet):
        """Match a multibyte unicode search term case-insensitively."""
        await seed_snippet(session, "cafe.sh", title="Café Menu")
        await seed_snippet(session, "plain.sh", title="Diner")

        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(search="café"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"cafe.sh"}

    async def test_empty_table_returns_zero_total(self, session):
        """Yield an empty page with a zero total for an empty table."""
        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(),
            pagination=Pagination(offset=0, limit=50),
        )

        assert page.total == 0
        assert page.items == []


@pytest.mark.asyncio
class TestSnippetManagerListServiceTypes:
    """Test the whole-dataset service-type facet in ``list_service_types``."""

    async def test_returns_sorted_distinct_trimmed_values(self, session, seed_snippet):
        """Return the sorted distinct trimmed service types across the table."""
        await seed_snippet(session, "a.sh", service_type="mysql")
        await seed_snippet(session, "b.sh", service_type="mongodb")
        await seed_snippet(session, "c.sh", service_type="  mysql  ")
        await seed_snippet(session, "d.sh", service_type="postgresql")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == ["mongodb", "mysql", "postgresql"]
        assert has_uncategorized is False

    async def test_flags_uncategorized_for_absent_or_blank_values(
        self, session, seed_snippet
    ):
        """Flag uncategorized when any snippet has an absent or blank service type."""
        await seed_snippet(session, "typed.sh", service_type="mysql")
        await seed_snippet(session, "absent.sh")
        await seed_snippet(session, "blank.sh", service_type="   ")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == ["mysql"]
        assert has_uncategorized is True

    async def test_orders_mixed_case_types_by_codepoint(self, session, seed_snippet):
        """Sort service types by Unicode codepoint, so uppercase precedes lowercase.

        The facet sorts with Python ``sorted``, which is case-sensitive; a
        deployment mixing ``MySQL`` and ``mongodb`` gets uppercase-first ordering.
        """
        await seed_snippet(session, "a.sh", service_type="MySQL")
        await seed_snippet(session, "b.sh", service_type="mongodb")
        await seed_snippet(session, "c.sh", service_type="Redis")

        service_types, _ = await SnippetManager.list_service_types(session)

        assert service_types == ["MySQL", "Redis", "mongodb"]

    async def test_empty_table_returns_no_types(self, session):
        """Return no service types and no uncategorized flag for an empty table."""
        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )

        assert service_types == []
        assert has_uncategorized is False


@pytest.mark.asyncio
class TestSnippetManagerServiceTypeNormalizationAgrees:
    """Pin the facet and the list filter to one whitespace-normalization definition.

    ``list_service_types`` and ``_list_query_filters`` both trim through
    :meth:`~app.sep.snippets.crud.SnippetManager._service_type_exprs`, so a value
    the facet reports as blank is exactly the value the Uncategorized filter
    selects, and a padded value the facet lists is exactly what the equality
    filter matches -- including tab/newline padding that SQL ``TRIM`` leaves
    intact but Python/JavaScript ``strip``/``trim`` would fold.
    """

    @pytest.mark.parametrize("whitespace", ["\t", "\n", "\r\n"])
    async def test_non_space_whitespace_value_is_a_real_type_on_both_paths(
        self, session, seed_snippet, whitespace
    ):
        """Keep a tab/newline-only service type as a real, selectable value."""
        await seed_snippet(session, "ws.sh", service_type=whitespace)
        await seed_snippet(session, "absent.sh")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            session
        )
        uncategorized_page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        # SQL TRIM leaves non-space whitespace intact, so the facet lists the value
        # and the Uncategorized filter excludes it -- the two paths agree.
        assert whitespace in service_types
        assert has_uncategorized is True
        assert [s.filename for s in uncategorized_page.items] == ["absent.sh"]

    async def test_tab_padded_value_matches_the_equality_filter(
        self, session, seed_snippet
    ):
        """Match a tab-padded stored value with the facet value the UI would send."""
        await seed_snippet(session, "padded.sh", service_type="mysql\t")
        await seed_snippet(session, "mongo.sh", service_type="mongodb")

        service_types, _ = await SnippetManager.list_service_types(session)
        page = await SnippetManager.snippet_list_page(
            session,
            list_query=SnippetListQuery(service_type="mysql\t"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert "mysql\t" in service_types
        assert [s.filename for s in page.items] == ["padded.sh"]


class TestSnippetListQueryOrderByRendering:
    """Cover the dialect-aware NULLs-last rendering of the snippets ORDER BY."""

    @pytest.mark.parametrize(
        "sort_key",
        [SnippetSortKey.TITLE, SnippetSortKey.FILENAME],
        ids=["meta_key", "column"],
    )
    @pytest.mark.parametrize(
        "sort_direction", list(SnippetSortDirection), ids=lambda value: value.value
    )
    def test_order_by_renders_mysql_isnull_idiom(self, sort_key, sort_direction):
        """Emit MySQL's ``ISNULL`` idiom instead of the unparsable ``NULLS LAST``."""
        order_by = SnippetManager._list_query_order_by(
            DatabaseDialect.MYSQL,
            SnippetListQuery(sort_key=sort_key, sort_direction=sort_direction),
        )

        rendered = str(
            select(col(Snippet.id)).order_by(*order_by).compile(dialect=mysql.dialect())
        )

        assert "NULLS LAST" not in rendered
        assert "ISNULL(" in rendered


@pytest.mark.asyncio
class TestSnippetManagerListQueryOnPostgres:
    """Exercise the dialect-specific JSON, trimming, and ordering SQL on PostgreSQL.

    SQLite is not a substitute for PostgreSQL for the ``->>`` JSON extract, the
    ``TRIM`` normalization, and NULL ordering, so these run against a real
    ``postgres_session`` (auto-skipped when ``SEP_TEST_POSTGRES_DSN`` is unset).
    """

    async def test_search_matches_json_title_and_description(
        self, postgres_session, seed_snippet
    ):
        """Search the ``meta`` JSON title/description via the ``->>`` extract."""
        await seed_snippet(postgres_session, "other.sh", title="MySQL Report")
        await seed_snippet(postgres_session, "third.sh", description="the MYSQL log")
        await seed_snippet(postgres_session, "skip.sh", title="Postgres")

        page = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(search="mysql"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"other.sh", "third.sh"}

    async def test_service_type_equality_matches_trimmed_value(
        self, postgres_session, seed_snippet
    ):
        """Match the trimmed stored ``meta.service_type`` on PostgreSQL."""
        await seed_snippet(postgres_session, "padded.sh", service_type="  mysql  ")
        await seed_snippet(postgres_session, "mongo.sh", service_type="mongodb")

        page = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(service_type="mysql"),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in page.items] == ["padded.sh"]

    async def test_uncategorized_selects_absent_and_blank(
        self, postgres_session, seed_snippet
    ):
        """Select absent/blank service types via the NULL-or-trimmed predicate."""
        await seed_snippet(postgres_session, "typed.sh", service_type="mysql")
        await seed_snippet(postgres_session, "absent.sh")
        await seed_snippet(postgres_session, "blank.sh", service_type="   ")

        page = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        assert {s.filename for s in page.items} == {"absent.sh", "blank.sh"}

    async def test_sort_by_meta_title_orders_by_json_value(
        self, postgres_session, seed_snippet
    ):
        """Order by the ``meta.title`` JSON value ascending on PostgreSQL."""
        await seed_snippet(postgres_session, "one.sh", title="Charlie")
        await seed_snippet(postgres_session, "two.sh", title="Alpha")
        await seed_snippet(postgres_session, "three.sh", title="Bravo")

        page = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.ASC
            ),
            pagination=Pagination(offset=0, limit=50),
        )

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

        ascending = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.ASC
            ),
            pagination=Pagination(offset=0, limit=50),
        )
        descending = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.DESC
            ),
            pagination=Pagination(offset=0, limit=50),
        )

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

        query = SnippetListQuery(
            sort_key=SnippetSortKey.SERVICE_TYPE,
            sort_direction=SnippetSortDirection.ASC,
        )
        first = await SnippetManager.snippet_list_page(
            postgres_session, list_query=query, pagination=Pagination(offset=0, limit=2)
        )
        second = await SnippetManager.snippet_list_page(
            postgres_session, list_query=query, pagination=Pagination(offset=2, limit=2)
        )

        assert [s.filename for s in first.items] == ["a.sh", "b.sh"]
        assert [s.filename for s in second.items] == ["c.sh", "d.sh"]

    async def test_facet_returns_sorted_distinct_trimmed_values(
        self, postgres_session, seed_snippet
    ):
        """Return the sorted distinct trimmed service types on PostgreSQL."""
        await seed_snippet(postgres_session, "a.sh", service_type="mysql")
        await seed_snippet(postgres_session, "c.sh", service_type="  mysql  ")
        await seed_snippet(postgres_session, "b.sh", service_type="mongodb")
        await seed_snippet(postgres_session, "absent.sh")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            postgres_session
        )

        assert service_types == ["mongodb", "mysql"]
        assert has_uncategorized is True

    async def test_tab_service_type_agrees_between_facet_and_filter(
        self, postgres_session, seed_snippet
    ):
        """Group a tab-only service type identically on the facet and the filter."""
        await seed_snippet(postgres_session, "ws.sh", service_type="\t")
        await seed_snippet(postgres_session, "absent.sh")

        service_types, has_uncategorized = await SnippetManager.list_service_types(
            postgres_session
        )
        uncategorized_page = await SnippetManager.snippet_list_page(
            postgres_session,
            list_query=SnippetListQuery(uncategorized=True),
            pagination=Pagination(offset=0, limit=50),
        )

        assert "\t" in service_types
        assert has_uncategorized is True
        assert [s.filename for s in uncategorized_page.items] == ["absent.sh"]


@pytest.mark.mysql
@pytest.mark.asyncio
class TestSnippetManagerListQueryOnMySQL:
    """Exercise the snippets NULLs-last ordering against a real MySQL bind.

    MySQL has no ``NULLS LAST`` syntax, so this path can only be verified on a real
    bind (auto-skipped when ``SEP_TEST_MYSQL_DSN`` is unset). The meta-title case
    asserts the same filename-order literals the PostgreSQL class does; the
    filename-sort case has no PostgreSQL counterpart, since it exists to cover the
    tie-breaker-free ordering where the construct is the entire ``ORDER BY``.
    """

    async def test_sort_by_meta_title_places_missing_titles_last(
        self, mysql_session, seed_snippet
    ):
        """Pin rows lacking ``meta.title`` last in both directions on MySQL.

        The sort expression is a JSON extract, so this also covers the extract
        nesting inside the ``ISNULL`` term rather than being evaluated once.
        """
        await seed_snippet(mysql_session, "alpha.sh", title="Alpha")
        await seed_snippet(mysql_session, "bravo.sh", title="Bravo")
        await seed_snippet(mysql_session, "no-title-1.sh")
        await seed_snippet(mysql_session, "no-title-2.sh")

        ascending = await SnippetManager.snippet_list_page(
            mysql_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.ASC
            ),
            pagination=Pagination(offset=0, limit=50),
        )
        descending = await SnippetManager.snippet_list_page(
            mysql_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.TITLE, sort_direction=SnippetSortDirection.DESC
            ),
            pagination=Pagination(offset=0, limit=50),
        )

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

    async def test_sort_by_filename_orders_without_tie_breaker(
        self, mysql_session, seed_snippet
    ):
        """Keep the non-nullable filename ordering correct without a tie-breaker.

        Filename is unique, so this ordering is the construct alone -- the ``ISNULL``
        term is a constant here and must not disturb the order in either direction.
        """
        for name in ("b.sh", "a.sh", "c.sh"):
            await seed_snippet(mysql_session, name)

        ascending = await SnippetManager.snippet_list_page(
            mysql_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.FILENAME,
                sort_direction=SnippetSortDirection.ASC,
            ),
            pagination=Pagination(offset=0, limit=50),
        )
        descending = await SnippetManager.snippet_list_page(
            mysql_session,
            list_query=SnippetListQuery(
                sort_key=SnippetSortKey.FILENAME,
                sort_direction=SnippetSortDirection.DESC,
            ),
            pagination=Pagination(offset=0, limit=50),
        )

        assert [s.filename for s in ascending.items] == ["a.sh", "b.sh", "c.sh"]
        assert [s.filename for s in descending.items] == ["c.sh", "b.sh", "a.sh"]

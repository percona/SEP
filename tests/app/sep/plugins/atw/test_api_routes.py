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

"""Tests for the ATW plugin JSON API routes under /api/plugins/atw/."""

from collections.abc import Iterator
from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.sep.main import sep_app
from app.sep.plugins.atw.models import ParentCategory
from app.sep.snippets.models import Snippet


@pytest.fixture
def unauthenticated_client() -> Iterator[TestClient]:
    """Yield a test client with authentication dependency overrides cleared."""
    previous = sep_app.dependency_overrides
    sep_app.dependency_overrides = {}
    try:
        yield TestClient(sep_app, raise_server_exceptions=False)
    finally:
        sep_app.dependency_overrides = previous


class TestAtwListEndpoint:
    """Tests for GET /api/plugins/atw/."""

    def test_atw_list_returns_grouped_snippets(self, test_client: TestClient):
        """Ensure the listing endpoint groups snippets by ATW category."""
        snippet = Mock()
        snippet.filename = "diag/slow-query.sh"
        snippet.title = "Slow Query Diagnostics"
        snippet.description = "Collects slow-query and processlist data."
        snippet.meta = {"atw": ["OVERALL_SLOWNESS"]}

        with patch(
            "app.sep.plugins.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/plugins/atw/")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        payload = response.json()
        assert isinstance(payload, list)
        overall = next(
            entry for entry in payload if entry["category"] == "OVERALL_SLOWNESS"
        )
        assert overall is not None
        assert overall["snippet_count"] == 1
        assert overall["category_root"] == "MySQL"
        assert overall["parent_category"] == "PERFORMANCE_ISSUES"
        assert overall["snippets"][0]["name"] == "diag/slow-query.sh"
        assert overall["snippets"][0]["snippet_schema_url"].endswith(
            "/plugins/snippets/diag%2Fslow-query.sh/schema"
        )

    def test_atw_list_real_snippet_row_meta_shape(
        self, test_client: TestClient
    ) -> None:
        """Integration guard: real ``Snippet`` + ``meta`` dict matches what the route reads."""
        snippet = Snippet(
            filename="diag/slow-query.sh",
            size=100,
            md5_digest="a" * 32,
            meta={
                "title": "Slow Query Diagnostics",
                "description": "Collects slow-query and processlist data.",
                "atw": ["OVERALL_SLOWNESS"],
            },
        )

        with patch(
            "app.sep.plugins.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/plugins/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        overall = next(
            entry for entry in payload if entry["category"] == "OVERALL_SLOWNESS"
        )
        assert overall["snippet_count"] == 1
        assert overall["snippets"][0]["name"] == "diag/slow-query.sh"
        assert overall["snippets"][0]["title"] == "Slow Query Diagnostics"
        assert overall["snippets"][0]["description"] == (
            "Collects slow-query and processlist data."
        )

    def test_atw_list_non_list_atw_meta_not_substring_matched(
        self, test_client: TestClient
    ) -> None:
        """Ignore ``meta["atw"]`` when it is not a list (avoids ``str`` substring ``in``)."""
        snippet = Mock()
        snippet.filename = "bad-meta.sh"
        snippet.title = "Bad meta"
        snippet.description = ""
        snippet.meta = {"atw": "noise OVERALL_SLOWNESS noise"}

        with patch(
            "app.sep.plugins.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/plugins/atw/")

        assert response.status_code == status.HTTP_200_OK
        overall = next(
            entry
            for entry in response.json()
            if entry["category"] == "OVERALL_SLOWNESS"
        )
        assert overall["snippet_count"] == 0

    def test_atw_percent_encoded_slash_in_snippet_url_not_routed_as_single_filename(
        self, test_client: TestClient
    ) -> None:
        """Regression guard: ``quote(..., safe='')`` turns ``/`` into ``%2F``.

        Many HTTP stacks decode ``%2F`` into a real path separator before routing,
        so ``GET .../diag%2Fslow-query.sh/schema`` does not match FastAPI's
        ``/{snippet_filename}/schema`` as one segment — unlike our string assertion
        on the listing payload alone (clients would see 404 or wrong matching).
        """
        snippet = Mock()
        snippet.filename = "diag/slow-query.sh"
        snippet.title = "Slow Query Diagnostics"
        snippet.description = "Collects slow-query and processlist data."
        snippet.meta = {"atw": ["OVERALL_SLOWNESS"]}

        with patch(
            "app.sep.plugins.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            listing = test_client.get("/api/plugins/atw/")

        assert listing.status_code == status.HTTP_200_OK
        overall = next(
            row
            for row in listing.json()
            if row["category"] == "OVERALL_SLOWNESS" and row["snippet_count"] > 0
        )
        schema_url = overall["snippets"][0]["snippet_schema_url"]
        assert "%2F" in schema_url

        probe = test_client.get(f"/api{schema_url}")
        assert probe.status_code == status.HTTP_404_NOT_FOUND

    def test_atw_list_requires_authentication(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Ensure unauthenticated callers receive JSON 401."""
        response = unauthenticated_client.get(
            "/api/plugins/atw/",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")


class TestAtwSchemaEndpoint:
    """Tests for GET /api/plugins/atw/schema."""

    def test_atw_schema_requires_authentication(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Ensure unauthenticated callers receive JSON 401 (mirrors list endpoint)."""
        response = unauthenticated_client.get(
            "/api/plugins/atw/schema",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    def test_atw_schema_returns_plugin_name(self, test_client: TestClient):
        """Ensure the schema endpoint serves the ATW plugin schema."""
        response = test_client.get("/api/plugins/atw/schema")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "atw"
        assert data["display_name"] == "Collect Diagnostic Data"

    def test_atw_schema_category_browser_has_parent_category_fail_rules(
        self, test_client: TestClient
    ) -> None:
        """Category Browser section exposes SEP-1071 fail_when for parent/category pairs."""
        response = test_client.get("/api/plugins/atw/schema")

        assert response.status_code == status.HTTP_200_OK
        section = response.json()["forms"][0]
        fail_when = section["fail_when"]
        assert isinstance(fail_when, list)
        expected_rules = 1 + len(ParentCategory)
        assert len(fail_when) == expected_rules
        assert "parent_category" in fail_when[0]["message"]

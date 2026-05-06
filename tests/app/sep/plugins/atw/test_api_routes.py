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

    def test_atw_schema_returns_plugin_name(self, test_client: TestClient):
        """Ensure the schema endpoint serves the ATW plugin schema."""
        response = test_client.get("/api/plugins/atw/schema")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "atw"
        assert data["display_name"] == "Collect Diagnostic Data"

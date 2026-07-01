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

"""Tests for the ATW plugin JSON API routes under /api/apps/atw/."""

from unittest.mock import AsyncMock, Mock, patch

from fastapi import status
from fastapi.testclient import TestClient

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.atw import api_routes as atw_api_routes
from app.sep.apps.atw.models import ATWCategory, CATEGORY_ROOT_LABELS, ParentCategory
from app.sep.snippets.models import Snippet

_GENERIC_ROOT = CATEGORY_ROOT_LABELS["generic"]


def _mock_atw_snippet(
    *,
    filename: str,
    title: str = "Title",
    description: str = "",
    atw: list[str],
    service_type: str | None = "mysql",
) -> Mock:
    snippet = Mock()
    snippet.filename = filename
    snippet.title = title
    snippet.description = description
    meta: dict = {"atw": atw}
    if service_type is not None:
        meta["service_type"] = service_type
    snippet.meta = meta
    return snippet


class TestAtwListEndpoint:
    """Tests for GET /api/apps/atw/."""

    def test_atw_list_returns_grouped_snippets(self, test_client: TestClient):
        """Ensure the listing endpoint groups mysql-tagged snippets under the MySQL root."""
        snippet = _mock_atw_snippet(
            filename="diag/slow-query.sh",
            title="Slow Query Diagnostics",
            description="Collects slow-query and processlist data.",
            atw=["OVERALL_SLOWNESS"],
            service_type="mysql",
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        payload = response.json()
        assert isinstance(payload, list)
        assert len(payload) == 1
        overall = next(
            entry for entry in payload if entry["category"] == "OVERALL_SLOWNESS"
        )
        assert overall is not None
        assert overall["snippet_count"] == 1
        assert overall["category_root"] == CATEGORY_ROOT_LABELS[ServiceTypeEnum.MYSQL]
        assert overall["parent_category"] == "PERFORMANCE_ISSUES"
        summary = overall["snippets"][0]
        assert summary["name"] == "diag/slow-query.sh"
        assert set(summary.keys()) == {"name", "title", "description"}

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
                "service_type": "mysql",
                "atw": ["OVERALL_SLOWNESS"],
            },
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == 1
        overall = next(
            entry for entry in payload if entry["category"] == "OVERALL_SLOWNESS"
        )
        assert overall["snippet_count"] == 1
        assert overall["category_root"] == CATEGORY_ROOT_LABELS[ServiceTypeEnum.MYSQL]
        assert overall["snippets"][0]["name"] == "diag/slow-query.sh"
        assert overall["snippets"][0]["title"] == "Slow Query Diagnostics"
        assert overall["snippets"][0]["description"] == (
            "Collects slow-query and processlist data."
        )

    def test_atw_list_multi_root_mysql_and_mongodb(
        self, test_client: TestClient
    ) -> None:
        """Ensure mysql and mongodb snippets produce separate ``category_root`` rows."""
        mysql_snippet = _mock_atw_snippet(
            filename="mysql/slow.sh",
            atw=["OVERALL_SLOWNESS"],
            service_type="mysql",
        )
        mongo_snippet = _mock_atw_snippet(
            filename="mongo/slow.sh",
            atw=["OVERALL_SLOWNESS"],
            service_type="mongodb",
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[mysql_snippet, mongo_snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        populated_types = (ServiceTypeEnum.MYSQL, ServiceTypeEnum.MONGODB)
        expected_roots = [
            CATEGORY_ROOT_LABELS[service_type]
            for service_type in CATEGORY_ROOT_LABELS
            if service_type in populated_types
        ]
        roots = [entry["category_root"] for entry in payload]
        assert roots == expected_roots
        for entry in payload:
            assert entry["category"] == "OVERALL_SLOWNESS"
            assert entry["snippet_count"] == 1

    def test_atw_list_generic_service_type_bucket(
        self, test_client: TestClient
    ) -> None:
        """Ensure ``service_type: generic`` snippets surface under the Generic root."""
        snippet = _mock_atw_snippet(
            filename="generic/disk.sh",
            atw=["OVERALL_SLOWNESS"],
            service_type="generic",
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["category_root"] == _GENERIC_ROOT

    def test_atw_list_missing_service_type_falls_back_to_generic(
        self, test_client: TestClient
    ) -> None:
        """Ensure missing ``service_type`` meta buckets under Generic, not MySQL."""
        snippet = _mock_atw_snippet(
            filename="no-service-type.sh",
            atw=["OVERALL_SLOWNESS"],
            service_type=None,
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["category_root"] == _GENERIC_ROOT
        assert payload[0]["category"] == "OVERALL_SLOWNESS"
        assert payload[0]["snippet_count"] == 1

    def test_atw_list_unknown_service_type_falls_back_to_generic(
        self, test_client: TestClient
    ) -> None:
        """Ensure unknown ``service_type`` values bucket under Generic, not MySQL."""
        snippet = _mock_atw_snippet(
            filename="unknown/engine.sh",
            atw=["GALERA"],
            service_type="clickhouse",
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == 1
        assert payload[0]["category_root"] == _GENERIC_ROOT
        assert payload[0]["category"] == "GALERA"

    def test_atw_list_omits_empty_root_category_cells(
        self, test_client: TestClient
    ) -> None:
        """Ensure empty (root, category) cells are omitted from the listing."""
        snippet = _mock_atw_snippet(
            filename="mysql/only.sh",
            atw=["OVERALL_SLOWNESS"],
            service_type="mysql",
        )

        with patch(
            "app.sep.apps.atw.api_routes.SnippetManager.list",
            new=AsyncMock(return_value=[snippet]),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert len(payload) == 1
        populated = {(e["category_root"], e["category"]) for e in payload}
        mysql_root = CATEGORY_ROOT_LABELS[ServiceTypeEnum.MYSQL]
        assert populated == {(mysql_root, "OVERALL_SLOWNESS")}
        for category in ATWCategory:
            if category.name != "OVERALL_SLOWNESS":
                assert (mysql_root, category.name) not in populated

    def test_atw_list_non_list_atw_meta_not_substring_matched(
        self, test_client: TestClient
    ) -> None:
        """Ignore ``meta["atw"]`` when it is not a list (avoids ``str`` substring ``in``)."""
        snippet = Mock()
        snippet.filename = "bad-meta.sh"
        snippet.title = "Bad meta"
        snippet.description = ""
        snippet.meta = {"atw": "noise OVERALL_SLOWNESS noise"}

        with (
            patch.object(atw_api_routes.logger, "warning") as warn_mock,
            patch(
                "app.sep.apps.atw.api_routes.SnippetManager.list",
                new=AsyncMock(return_value=[snippet]),
            ),
        ):
            response = test_client.get("/api/apps/atw/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        warn_mock.assert_called_once_with(
            "Ignoring meta['atw'] for snippet %s: expected list, got %s",
            "bad-meta.sh",
            "str",
        )

    def test_atw_list_requires_authentication(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Ensure unauthenticated callers receive JSON 401."""
        response = unauthenticated_client.get(
            "/api/apps/atw/",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")


class TestAtwSchemaEndpoint:
    """Tests for GET /api/apps/atw/schema."""

    def test_atw_schema_requires_authentication(
        self, unauthenticated_client: TestClient
    ) -> None:
        """Ensure unauthenticated callers receive JSON 401 (mirrors list endpoint)."""
        response = unauthenticated_client.get(
            "/api/apps/atw/schema",
            follow_redirects=False,
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.headers["content-type"].startswith("application/json")

    def test_atw_schema_returns_plugin_name(self, test_client: TestClient):
        """Ensure the schema endpoint serves the ATW plugin schema."""
        response = test_client.get("/api/apps/atw/schema")

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == "atw"
        assert data["display_name"] == "Collect Diagnostic Data"

    def test_atw_schema_category_browser_has_parent_category_fail_rules(
        self, test_client: TestClient
    ) -> None:
        """Verify the Category Browser section exposes fail_when for parent/category pairs."""
        response = test_client.get("/api/apps/atw/schema")

        assert response.status_code == status.HTTP_200_OK
        section = response.json()["forms"][0]
        fail_when = section["fail_when"]
        assert isinstance(fail_when, list)
        expected_rules = 1 + len(ParentCategory)
        assert len(fail_when) == expected_rules
        assert "parent_category" in fail_when[0]["message"]

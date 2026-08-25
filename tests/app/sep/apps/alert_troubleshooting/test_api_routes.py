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

"""HTTP integration tests for the alert_troubleshooting plugin JSON API routes."""

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from tests.app.sep.apps.snippet_kit import persist_meta

API_BASE = "/api/apps/alert_troubleshooting"
EXPECTED_GROUP_COUNT = 2


@pytest.mark.asyncio
class TestAlertTroubleshootingApiList:
    """Tests for ``GET /api/apps/alert_troubleshooting/``."""

    async def test_returns_empty_list_when_no_snippets(
        self, api_client: TestClient, session: AsyncSession, snippets_dir
    ):
        """No snippets with alert meta → empty groups list."""
        response = api_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    async def test_returns_grouped_alerts(
        self,
        api_client: TestClient,
        session: AsyncSession,
        create_snippet_with_alerts,
        snippets_dir,
    ):
        """Snippets with alert meta are grouped by service type."""
        await create_snippet_with_alerts(
            "mysql_check.sh",
            alerts=["MySQLSlowQueries"],
            service_type="mysql",
        )
        await create_snippet_with_alerts(
            "mongo_check.sh",
            alerts=["MongoDBReplicaLag"],
            service_type="mongodb",
        )

        response = api_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert len(body) == EXPECTED_GROUP_COUNT
        service_types = {group["service_type"] for group in body}
        assert "mysql" in service_types
        assert "mongodb" in service_types
        labels_by_type = {group["service_type"]: group["label"] for group in body}
        assert labels_by_type["mysql"] == "MySQL"
        assert labels_by_type["mongodb"] == "MongoDB"

    async def test_alerts_include_snippet_count(
        self,
        api_client: TestClient,
        session: AsyncSession,
        create_snippet_with_alerts,
        snippets_dir,
    ):
        """Each alert group contains alert summaries with name and label."""
        await create_snippet_with_alerts(
            "mysql_check.sh",
            alerts=["MySQLSlowQueries"],
            service_type="mysql",
        )

        response = api_client.get(f"{API_BASE}/")

        body = response.json()
        mysql_group = next(g for g in body if g["service_type"] == "mysql")
        assert len(mysql_group["alerts"]) == 1
        alert = mysql_group["alerts"][0]
        assert alert["name"] == "MySQLSlowQueries"
        assert alert["label"] == "MySQL Slow Queries"

    async def test_requires_authentication(self, unauthenticated_client, snippets_dir):
        """Unauthenticated requests return 401."""
        response = unauthenticated_client.get(f"{API_BASE}/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
class TestAlertTroubleshootingApiDetail:
    """Tests for ``GET /api/apps/alert_troubleshooting/{service_type}/{alert_name}``."""

    async def test_returns_alert_and_snippets(
        self,
        api_client: TestClient,
        session: AsyncSession,
        create_snippet_with_alerts,
        snippets_dir,
    ):
        """Detail endpoint returns alert info and associated snippets."""
        await create_snippet_with_alerts(
            "mysql_check.sh",
            alerts=["MySQLSlowQueries"],
            service_type="mysql",
        )

        response = api_client.get(f"{API_BASE}/mysql/MySQLSlowQueries")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert "alert" in body
        assert "snippets" in body
        assert body["alert"]["name"] == "MySQLSlowQueries"
        assert len(body["snippets"]) == 1
        assert body["snippets"][0]["filename"] == "mysql_check.sh"

    @pytest.mark.parametrize("declared_description", [None, "", "   "])
    async def test_blank_declared_description_reads_as_empty(
        self,
        api_client: TestClient,
        session: AsyncSession,
        create_snippet_with_alerts,
        snippets_dir,
        declared_description,
    ):
        """Return an empty description rather than failing the whole detail view."""
        snippet = await create_snippet_with_alerts(
            "mysql_check.sh",
            alerts=["MySQLSlowQueries"],
            service_type="mysql",
        )
        await persist_meta(session, snippet, {"description": declared_description})

        response = api_client.get(f"{API_BASE}/mysql/MySQLSlowQueries")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["snippets"][0]["description"] == ""

    async def test_returns_404_for_unknown_alert(
        self,
        api_client: TestClient,
        session: AsyncSession,
        snippets_dir,
    ):
        """Unknown alert name returns 404."""
        response = api_client.get(f"{API_BASE}/mysql/NonExistentAlert")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_404_for_wrong_service_type(
        self,
        api_client: TestClient,
        session: AsyncSession,
        create_snippet_with_alerts,
        snippets_dir,
    ):
        """Alert under wrong service type returns 404."""
        await create_snippet_with_alerts(
            "mysql_check.sh",
            alerts=["MySQLSlowQueries"],
            service_type="mysql",
        )

        response = api_client.get(f"{API_BASE}/mongodb/MySQLSlowQueries")

        assert response.status_code == status.HTTP_404_NOT_FOUND

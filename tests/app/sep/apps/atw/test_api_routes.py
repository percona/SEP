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

import re
from datetime import timedelta
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import status
from fastapi.testclient import TestClient
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth.providers.casdoor.models import CasdoorUser
from app.core.utils.date_time import utc_now
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.atw import api_routes as atw_api_routes
from app.sep.apps.atw.categories import (
    ATWCategory,
    CATEGORY_ROOT_LABELS,
    ParentCategory,
)
from app.sep.apps.atw.crud import AtwIncidentExecutionManager, AtwIncidentManager
from app.sep.apps.atw.models import (
    AtwIncident,
    AtwIncidentExecution,
    AtwIncidentResponse,
)
from app.sep.deps import BEARER_REQUIRED_DETAIL
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


INCIDENTS_BASE = "/api/apps/atw/incidents/"
_INCIDENT_NAME_PATTERN = r"Incident \d{4}-\d\d-\d\d \d\d:\d\d"


@pytest_asyncio.fixture
async def seeded_incidents(session: AsyncSession) -> list[AtwIncident]:
    """Seed two incidents with distinct creation times (returned newest-first)."""
    older = await AtwIncidentManager.save(
        session,
        AtwIncident(
            created_by="alice",
            name="older",
            created_at=utc_now() - timedelta(minutes=1),
        ),
    )
    newer = await AtwIncidentManager.save(
        session,
        AtwIncident(created_by="alice", name="newer", created_at=utc_now()),
    )
    return [newer, older]


@pytest_asyncio.fixture
async def seeded_incident(session: AsyncSession) -> AtwIncident:
    """Seed one incident with a known name and support-case reference."""
    return await AtwIncidentManager.save(
        session,
        AtwIncident(created_by="alice", name="Original", case_ref="SN-1"),
    )


@pytest_asyncio.fixture
async def incident_with_executions(session: AsyncSession) -> AtwIncident:
    """Seed one incident owning two execution rows."""
    incident = await AtwIncidentManager.save(
        session, AtwIncident(created_by="alice", name="With executions")
    )
    for task_history_id in (1, 2):
        await AtwIncidentExecutionManager.save(
            session,
            AtwIncidentExecution(
                incident_id=incident.id,
                task_history_id=task_history_id,
                snippet_filename="diag.sh",
            ),
        )
    return incident


class TestAtwIncidentCreate:
    """Check the POST /api/apps/atw/incidents/ route."""

    def test_create_without_name_generates_default(
        self, api_client: TestClient, regular_user: CasdoorUser
    ) -> None:
        """Ensure an omitted name gets the server default and created_by is stamped."""
        response = api_client.post(INCIDENTS_BASE, json={})

        assert response.status_code == status.HTTP_201_CREATED
        payload = response.json()
        assert re.fullmatch(_INCIDENT_NAME_PATTERN, payload["name"])
        assert payload["created_by"] == regular_user.username
        assert payload["case_ref"] is None

    def test_create_with_custom_fields_echoes_values(
        self, api_client: TestClient
    ) -> None:
        """Ensure a custom name and case persist and a UUID id is returned."""
        response = api_client.post(
            INCIDENTS_BASE,
            json={"name": "Prod outage", "case_ref": "CS123"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        payload = response.json()
        assert payload["name"] == "Prod outage"
        assert payload["case_ref"] == "CS123"
        assert UUID(payload["id"])

    def test_create_cookie_only_is_rejected(
        self, cookie_only_client: TestClient
    ) -> None:
        """Ensure a cookie-only create (no Bearer header) is rejected with 401."""
        response = cookie_only_client.post(INCIDENTS_BASE, json={"name": "x"})

        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        assert response.json()["detail"] == BEARER_REQUIRED_DETAIL


class TestAtwIncidentList:
    """Check the GET /api/apps/atw/incidents/ listing route."""

    def test_list_returns_incidents_newest_first(
        self, api_client: TestClient, seeded_incidents: list[AtwIncident]
    ) -> None:
        """Ensure the listing paginates and orders incidents newest-first."""
        response = api_client.get(INCIDENTS_BASE)

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["total"] == len(seeded_incidents)
        assert [item["name"] for item in payload["items"]] == ["newer", "older"]

    def test_list_empty_returns_zero_total(self, api_client: TestClient) -> None:
        """Ensure an empty listing returns an empty page with a zero total."""
        response = api_client.get(INCIDENTS_BASE)

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["items"] == []
        assert payload["total"] == 0

    def test_list_pagination_window_echoed(
        self, api_client: TestClient, seeded_incidents: list[AtwIncident]
    ) -> None:
        """Ensure offset/limit narrow the page and are echoed in the envelope."""
        response = api_client.get(INCIDENTS_BASE, params={"limit": 1, "offset": 1})

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["total"] == len(seeded_incidents)
        assert len(payload["items"]) == 1
        assert payload["offset"] == 1
        assert payload["limit"] == 1
        assert payload["items"][0]["name"] == "older"

    @pytest.mark.parametrize(
        "params",
        [{"limit": 0}, {"offset": -1}, {"limit": 999}],
    )
    def test_list_rejects_out_of_bounds_pagination(
        self, api_client: TestClient, params: dict[str, int]
    ) -> None:
        """Ensure pagination bounds (limit 1-200, offset >= 0) are enforced."""
        response = api_client.get(INCIDENTS_BASE, params=params)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestAtwIncidentRetrieve:
    """Check the GET /api/apps/atw/incidents/{incident_id} route."""

    def test_get_existing_incident(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure an existing incident is retrievable by id."""
        response = api_client.get(f"{INCIDENTS_BASE}{seeded_incident.id}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["id"] == str(seeded_incident.id)

    def test_get_unknown_incident_returns_404(self, api_client: TestClient) -> None:
        """Ensure a random incident id returns 404."""
        response = api_client.get(f"{INCIDENTS_BASE}{uuid4()}")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAtwIncidentUpdate:
    """Check the PATCH /api/apps/atw/incidents/{incident_id} route."""

    def test_rename_leaves_case_ref_untouched(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure a name-only PATCH does not clear the untouched case reference."""
        response = api_client.patch(
            f"{INCIDENTS_BASE}{seeded_incident.id}", json={"name": "Renamed"}
        )

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["name"] == "Renamed"
        assert payload["case_ref"] == "SN-1"

    def test_set_case_ref_leaves_name_untouched(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure a case-only PATCH does not overwrite the untouched name."""
        response = api_client.patch(
            f"{INCIDENTS_BASE}{seeded_incident.id}",
            json={"case_ref": "CS999"},
        )

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["case_ref"] == "CS999"
        assert payload["name"] == "Original"

    def test_empty_name_is_rejected(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure renaming to an empty string is rejected by NonEmptyStr."""
        response = api_client.patch(
            f"{INCIDENTS_BASE}{seeded_incident.id}", json={"name": ""}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_explicit_null_name_is_rejected_without_touching_db(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure an explicit null name is a 422 (not a 500) and leaves the DB intact."""
        response = api_client.patch(
            f"{INCIDENTS_BASE}{seeded_incident.id}", json={"name": None}
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        unchanged = api_client.get(f"{INCIDENTS_BASE}{seeded_incident.id}")
        assert unchanged.json()["name"] == "Original"

    def test_update_unknown_incident_returns_404(self, api_client: TestClient) -> None:
        """Ensure updating a random incident id returns 404."""
        response = api_client.patch(f"{INCIDENTS_BASE}{uuid4()}", json={"name": "x"})

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestAtwIncidentDelete:
    """Check the DELETE /api/apps/atw/incidents/{incident_id} route."""

    def test_delete_existing_incident(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure deleting an existing incident returns 204."""
        response = api_client.delete(f"{INCIDENTS_BASE}{seeded_incident.id}")

        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_unknown_incident_returns_404(self, api_client: TestClient) -> None:
        """Ensure deleting a random incident id returns 404."""
        response = api_client.delete(f"{INCIDENTS_BASE}{uuid4()}")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.asyncio
    async def test_delete_cascades_execution_rows(
        self,
        async_api_client: AsyncClient,
        session: AsyncSession,
        incident_with_executions: AtwIncident,
    ) -> None:
        """Ensure deleting an incident cascades away its execution rows."""
        response = await async_api_client.delete(
            f"{INCIDENTS_BASE}{incident_with_executions.id}"
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        remaining = await AtwIncidentExecutionManager.count(
            session, incident_id=incident_with_executions.id
        )
        assert remaining == 0


class TestAtwIncidentCloseReopen:
    """Check close and reopen action routes."""

    def test_close_stamps_closed_at(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure closing an open incident stamps closed_at and returns it."""
        response = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/close/")

        assert response.status_code == status.HTTP_200_OK
        payload = response.json()
        assert payload["closed_at"] is not None
        assert payload["id"] == str(seeded_incident.id)

    def test_double_close_returns_409_and_preserves_stamp(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure closing an already-closed incident is rejected without changing the stamp."""
        first = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/close/")
        assert first.status_code == status.HTTP_200_OK
        first_stamp = first.json()["closed_at"]

        second = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/close/")

        assert second.status_code == status.HTTP_409_CONFLICT
        unchanged = api_client.get(f"{INCIDENTS_BASE}{seeded_incident.id}")
        assert unchanged.json()["closed_at"] == first_stamp

    def test_reopen_clears_closed_at(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure reopening a closed incident clears closed_at."""
        close_response = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/close/")
        assert close_response.status_code == status.HTTP_200_OK

        response = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/reopen/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["closed_at"] is None

    def test_double_reopen_returns_409(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure reopening an already-open incident is rejected."""
        response = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/reopen/")

        assert response.status_code == status.HTTP_409_CONFLICT

    def test_patch_and_delete_still_work_when_closed(
        self, api_client: TestClient, seeded_incident: AtwIncident
    ) -> None:
        """Ensure rename and delete remain available on a closed incident."""
        close_response = api_client.post(f"{INCIDENTS_BASE}{seeded_incident.id}/close/")
        assert close_response.status_code == status.HTTP_200_OK

        patch_response = api_client.patch(
            f"{INCIDENTS_BASE}{seeded_incident.id}", json={"name": "Closed but renamed"}
        )
        assert patch_response.status_code == status.HTTP_200_OK
        assert patch_response.json()["name"] == "Closed but renamed"

        delete_response = api_client.delete(f"{INCIDENTS_BASE}{seeded_incident.id}")
        assert delete_response.status_code == status.HTTP_204_NO_CONTENT

    @pytest.mark.asyncio
    async def test_close_handler_returns_response_model(
        self, session: AsyncSession, seeded_incident: AtwIncident
    ) -> None:
        """Return a stamped ``AtwIncidentResponse`` when closing an open incident."""
        result = await atw_api_routes.atw_close_incident(session, seeded_incident)

        assert isinstance(result, AtwIncidentResponse)
        assert result.closed_at is not None
        assert result.id == seeded_incident.id

    @pytest.mark.asyncio
    async def test_reopen_handler_returns_response_model(
        self, session: AsyncSession, seeded_incident: AtwIncident
    ) -> None:
        """Return a cleared ``AtwIncidentResponse`` when reopening a closed incident."""
        seeded_incident.closed_at = utc_now()
        closed = await AtwIncidentManager.save(session, seeded_incident)

        result = await atw_api_routes.atw_reopen_incident(session, closed)

        assert isinstance(result, AtwIncidentResponse)
        assert result.closed_at is None
        assert result.id == seeded_incident.id

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

"""Tests for the archives plugin JSON API routes under /api/plugins/archives/."""

from datetime import datetime, UTC
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import status

from app.core.exceptions import HTTPNotFoundException
from app.core.requests import RemoteAPI
from app.sep.deps import get_inventory_api, get_tasks_api
from app.sep.main import sep_app
from app.sep.plugins.archives.deps import build_archives_api_task_payload
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner

# ── Helpers ──────────────────────────────────────────────────────────────────


def build_archive_task(name: str = "test-archive") -> dict[str, Any]:
    """Return a minimal task dict shaped like the Tasks API response."""
    return {
        "id": 1,
        "name": name,
        "backend": TaskBackendEnum.PROXY,
        "owner": TaskOwner.ARCHIVER,
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
        "data": {
            "task": "run-python",
            "meta": {
                "target": "executor-host",
                "_service_name": "test-service",
                "config": "ALL:\n  SOURCE_HOST: 127.0.0.1\n  SOURCE_PORT: 3306\nPURGE_LIST: []\n",
            },
        },
        "created_at": datetime.now(UTC),
        "updated_at": None,
        "created_by": "user@example.com",
        "last_updated_by": "user@example.com",
    }


def build_valid_create_body(**overrides: Any) -> dict[str, Any]:
    """Return a JSON body that passes all ArchivesCreate validators.

    Uses swap_drop=0 (PURGE_ONLY) which requires a ``where`` clause but
    no destination host and no swp_table_suffix.
    """
    return {
        "alias": "test-archive",
        "hostname": "executor-host",
        "service_id": 1,
        "source_db_id": 10,
        "source_table_id": 20,
        "swap_drop": 0,
        "where": "id > 100",
        "dest_table_id": 30,
        **overrides,
    }


@pytest.fixture
def mock_tasks_api_dep() -> AsyncMock:
    """Mock the TaskAPI dependency for archives API route tests."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_tasks_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides.pop(get_tasks_api, None)


@pytest.fixture
def mock_inventory_api_dep_archives() -> AsyncMock:
    """Mock the InventoryAPI dependency for archives API route tests."""
    mock = AsyncMock(spec=RemoteAPI)
    sep_app.dependency_overrides[get_inventory_api] = lambda: mock
    yield mock
    sep_app.dependency_overrides.pop(get_inventory_api, None)


class TestArchivesApiAuthGuards:
    """Every archive API route must require authentication."""

    def test_list_unauthenticated(self, unauthenticated_client):
        """GET /api/plugins/archives/ without auth → 401."""
        response = unauthenticated_client.get("/api/plugins/archives/")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_detail_unauthenticated(self, unauthenticated_client):
        """GET /api/plugins/archives/{name} without auth → 401."""
        response = unauthenticated_client.get("/api/plugins/archives/test-archive")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_create_unauthenticated(self, unauthenticated_client):
        """POST /api/plugins/archives/ without auth → 401."""
        response = unauthenticated_client.post(
            "/api/plugins/archives/",
            json=build_valid_create_body(),
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_delete_unauthenticated(self, unauthenticated_client):
        """DELETE /api/plugins/archives/{name} without auth → 401."""
        response = unauthenticated_client.delete("/api/plugins/archives/test-archive")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


class TestArchivesApiList:
    """Tests for GET /api/plugins/archives/."""

    def test_list_returns_ok(self, test_client, mock_tasks_api_dep):
        """GET /api/plugins/archives/ returns 200 JSON array with batch statuses."""
        task = build_archive_task()
        mock_tasks_api_dep.get.return_value = {
            "items": [task],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        mock_tasks_api_dep.post.return_value = {
            task["name"]: TaskHistoryStatusEnum.SUCCESS.value
        }
        response = test_client.get("/api/plugins/archives/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 1
        assert data[0]["name"] == task["name"]
        assert data[0]["service_type"] == "mysql"
        assert data[0]["status"] == TaskHistoryStatusEnum.SUCCESS.value
        mock_tasks_api_dep.post.assert_awaited_once_with(
            "/history/latest", json={"names": [task["name"]]}
        )

    def test_list_empty(self, test_client, mock_tasks_api_dep):
        """GET /api/plugins/archives/ returns empty list when no tasks."""
        mock_tasks_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/plugins/archives/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_list_degrades_to_null_status_when_batch_status_errors(
        self, test_client, mock_tasks_api_dep
    ):
        """GET /api/plugins/archives/ stays 200 with null statuses on batch error."""
        task = build_archive_task()
        mock_tasks_api_dep.get.return_value = {
            "items": [task],
            "total": 1,
            "offset": 0,
            "limit": 50,
        }
        mock_tasks_api_dep.post.side_effect = RuntimeError("batch status upstream down")
        response = test_client.get("/api/plugins/archives/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] is None


# ── Detail ────────────────────────────────────────────────────────────────────


class TestArchivesApiDetail:
    """Tests for GET /api/plugins/archives/{task_name}."""

    def test_detail_returns_ok(self, test_client, mock_tasks_api_dep):
        """GET /api/plugins/archives/{name} returns 200 for existing task."""
        task = build_archive_task("my-archive")
        mock_tasks_api_dep.get.side_effect = [task, {"items": []}]
        response = test_client.get("/api/plugins/archives/my-archive")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "my-archive"
        assert body["service_type"] == "mysql"
        assert body["status"] is None

    def test_detail_returns_404_for_unknown_task(self, test_client, mock_tasks_api_dep):
        """GET /api/plugins/archives/{name} returns 404 for unknown task."""
        mock_tasks_api_dep.get.side_effect = HTTPNotFoundException("not found")
        response = test_client.get("/api/plugins/archives/does-not-exist")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestArchivesApiCreate:
    """Tests for POST /api/plugins/archives/."""

    def test_create_returns_201(
        self,
        test_client,
        mock_tasks_api_dep,
        generated_task,
    ):
        """POST with valid body → 201 and task name in response.

        Overrides the build_archives_api_task_payload dep to avoid wiring
        up real inventory mocks (verified separately in test_deps.py).
        """
        sep_app.dependency_overrides[build_archives_api_task_payload] = (
            lambda: generated_task
        )
        try:
            task = build_archive_task(generated_task.name)
            mock_tasks_api_dep.post.return_value = task

            response = test_client.post(
                "/api/plugins/archives/",
                json=build_valid_create_body(),
            )
            assert response.status_code == status.HTTP_201_CREATED
            assert response.json()["name"] == generated_task.name
        finally:
            sep_app.dependency_overrides.pop(build_archives_api_task_payload, None)


# ── Delete ────────────────────────────────────────────────────────────────────


class TestArchivesApiDelete:
    """Tests for DELETE /api/plugins/archives/{task_name}."""

    def test_delete_returns_204(self, test_client, mock_tasks_api_dep):
        """DELETE /api/plugins/archives/{name} → 204 on success."""
        task = build_archive_task("my-archive")
        mock_tasks_api_dep.get.return_value = task
        mock_tasks_api_dep.delete.return_value = None
        response = test_client.delete("/api/plugins/archives/my-archive")
        assert response.status_code == status.HTTP_204_NO_CONTENT

    def test_delete_returns_404_for_unknown_task(self, test_client, mock_tasks_api_dep):
        """DELETE /api/plugins/archives/{name} → 404 for unknown task."""
        mock_tasks_api_dep.get.side_effect = HTTPNotFoundException("not found")
        response = test_client.delete("/api/plugins/archives/does-not-exist")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestArchivesApiConditionalRules422:
    """One parametrised 422 test per declarative rule / validator.

    These fire at request-body validation time (before any dep runs).
    No inventory/tasks mock needed.
    """

    @pytest.mark.parametrize(
        ("overrides", "expected_in_detail"),
        [
            # Validator 1: same source_table_id and dest_table_id
            pytest.param(
                {"source_table_id": 5, "dest_table_id": 5},
                "same",
                id="same-table-ids",
            ),
            # Validator 2: dest_file set when swap_drop==SWAP_DROP (1)
            pytest.param(
                {
                    "swap_drop": 1,
                    "source_table_id": 5,
                    "dest_file": "/tmp/out.csv",
                    "dest_table_id": None,
                    "where": None,
                },
                "dest",
                id="dest-file-when-swap-drop",
            ),
            # Validator 3: dest_service_id and dest_host both set
            pytest.param(
                {"dest_service_id": 99, "dest_host": "other.host"},
                "dest_service_id",
                id="dest-service-and-host-conflict",
            ),
            # Validator 3c: dest_service_id selected + a manual dest_port
            pytest.param(
                {"dest_service_id": 99, "dest_port": 3307},
                "dest_port",
                id="dest-service-and-port-conflict",
            ),
            # Validator 4: SWAP_ARCHIVE_DROP without swp_table_suffix
            pytest.param(
                {
                    "swap_drop": 2,
                    "swp_table_suffix": None,
                    "dest_table_id": None,
                    "dest_file": None,
                },
                "swp_table_suffix",
                id="swap-archive-drop-no-suffix",
            ),
            # Validator 5: source_query and source_db_id both set
            pytest.param(
                {"source_query": "SELECT id FROM t WHERE id > 1", "source_db_id": 10},
                "source",
                id="source-query-and-ids-conflict",
            ),
            # Validator 6: where set when swap_drop==SWAP_DROP (1)
            pytest.param(
                {
                    "swap_drop": 1,
                    "where": "id > 1",
                    "dest_table_id": None,
                    "dest_file": None,
                },
                "where",
                id="where-set-when-swap-drop",
            ),
        ],
    )
    def test_rule_422(
        self,
        test_client,
        overrides: dict,
        expected_in_detail: str,
    ):
        """Each invalid payload produces 422 and mentions the relevant field(s)."""
        body = build_valid_create_body(**overrides)
        response = test_client.post("/api/plugins/archives/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, (
            f"Expected 422 for {overrides!r}, got {response.status_code}: "
            f"{response.text[:500]}"
        )
        detail_str = str(response.json().get("detail", "")).lower()
        assert expected_in_detail.lower() in detail_str, (
            f"Expected '{expected_in_detail}' in 422 detail, got: {detail_str[:300]}"
        )

    def test_multiple_rule_violations_report_all(self, test_client):
        """A payload violating 2 rules at once surfaces both in the 422 detail."""
        body = build_valid_create_body(
            # Validator 3a: dest_service_id AND dest_host both set
            dest_service_id=99,
            dest_host="conflict.host",
            # Validator 3b: dest_db_id AND dest_db_name both set
            dest_db_id=50,
            dest_db_name="conflict_db",
        )
        response = test_client.post("/api/plugins/archives/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = str(response.json()["detail"]).lower()
        assert "dest_service_id" in detail or "dest_host" in detail
        assert "dest_db_id" in detail or "dest_db_name" in detail

    def test_empty_string_source_table_id_coerced_to_none(self, test_client):
        """source_table_id='' is coerced to None, not treated as int 0."""
        body = build_valid_create_body(source_table_id="", source_db_id="")
        # With source_table_id and source_db_id coerced to None, there's no valid
        # source identifier → should get 422 (validator 5: missing source).
        response = test_client.post("/api/plugins/archives/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        detail = str(response.json().get("detail", "")).lower()
        assert "source" in detail, (
            f"Expected 'source' in 422 detail, got: {detail[:300]}"
        )

    def test_same_source_dest_table_names_returns_422(self, test_client):
        """Validator 1b: same host + same schema + same table name → 422.

        ``build_valid_create_body`` leaves the destination host/schema unset, so
        the destination defaults to the source host and schema — making this the
        genuine self-archive case that must still be rejected.
        """
        body = build_valid_create_body(
            source_db_id=None,
            source_table_id=None,
            source_db_name="mydb",
            source_table_name="users",
            dest_table_id=None,
            dest_table_name="users",
        )
        response = test_client.post("/api/plugins/archives/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, (
            f"Expected 422, got {response.status_code}: {response.text[:500]}"
        )
        detail = str(response.json()["detail"]).lower()
        assert (
            "same" in detail
            or "source_table_name" in detail
            or "dest_table_name" in detail
        ), f"Expected 'same' or table-name field in 422 detail, got: {detail[:300]}"

    def test_different_dest_host_same_table_name_allowed(
        self,
        test_client,
        mock_inventory_api_dep_archives,
        mock_tasks_api_dep,
        created_service,
    ):
        """Allow a different destination host that reuses the source table name.

        The destination is a distinct table, so the request is no longer
        rejected as a self-archive. Mocks only the inventory (source-service
        lookup) and tasks (post) boundaries so the real ``ArchivesCreate`` body
        model — and thus Validator 1b — is exercised through FastAPI's body
        parsing.
        """
        mock_inventory_api_dep_archives.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_tasks_api_dep.post.return_value = build_archive_task()
        body = build_valid_create_body(
            source_db_id=None,
            source_table_id=None,
            source_db_name="sbtest",
            source_table_name="sbtest5",
            dest_table_id=None,
            dest_table_name="sbtest5",
            dest_host="other-host",
        )
        response = test_client.post("/api/plugins/archives/", json=body)
        assert response.status_code == status.HTTP_201_CREATED, (
            f"Expected 201, got {response.status_code}: {response.text[:500]}"
        )
        assert "cannot be the same" not in response.text.lower()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            pytest.param("dest_host", "evil,host", id="dest-host-comma"),
            pytest.param("dest_host", "host=value", id="dest-host-equals"),
            pytest.param("dest_db_name", "key=value", id="dest-db-name-equals"),
            pytest.param("dest_db_name", "a,b", id="dest-db-name-comma"),
        ],
    )
    def test_dsn_delimiters_rejected(self, test_client, field: str, value: str):
        """validate_no_dsn_delimiters: ',' or '=' in dest_host/dest_db_name → 422."""
        body = build_valid_create_body(**{field: value})
        response = test_client.post("/api/plugins/archives/", json=body)
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY, (
            f"Expected 422 for {field}={value!r}, got {response.status_code}: "
            f"{response.text[:500]}"
        )
        detail = str(response.json()["detail"]).lower()
        assert "delimiter" in detail or "dsn" in detail or field in detail, (
            f"Expected DSN-delimiter rejection mention in 422 detail, got: {detail[:300]}"
        )

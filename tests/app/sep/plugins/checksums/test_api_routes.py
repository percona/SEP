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

"""Tests for the checksums plugin JSON API routes under /api/plugins/checksums/."""

import shlex
from datetime import datetime, UTC
from unittest.mock import AsyncMock, call, patch

import pytest
from fastapi import status

from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPConflictException,
    HTTPNotFoundException,
)
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import (
    clear_connectivity_caches,
    get_latest_connectivity_result,
)
from app.sep.deps import check_for_conflicted_running_tasks
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


def build_checksum_task(
    name: str = "checksum-task", *, with_connectivity_meta: bool = False
) -> dict:
    """Build a fake checksums task payload for route tests.

    :param name: The task name to embed in the payload.
    :type name: str
    :param with_connectivity_meta: If ``True``, populate the
        ``_connectivity_*`` meta keys consumed by the JSON-side connectivity
        helper. Defaults to ``False`` to preserve existing test behavior.
    :type with_connectivity_meta: bool
    :return: A task payload shaped like the Tasks API response.
    :rtype: dict
    """
    meta = {
        "command": "pt-table-checksum",
        "args": "--recursion-method=processlist",
        "target": "host1",
        "_service_name": "test-service",
        "_service_host": "127.0.0.1",
        "_service_port": 3306,
    }
    if with_connectivity_meta:
        meta["_connectivity_host"] = "127.0.0.1"
        meta["_connectivity_port"] = 3306
        meta["_connectivity_service_type"] = "mysql"
    return {
        "id": 1,
        "name": name,
        "backend": TaskBackendEnum.PROXY,
        "owner": TaskOwner.CHECKSUMS,
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
        "data": {"task": "run-command", "meta": meta},
        "created_at": datetime.now(UTC),
        "updated_at": None,
        "created_by": "user@example.com",
        "last_updated_by": "user@example.com",
    }


@pytest.fixture(autouse=True)
def _clear_connectivity_caches():
    """Clear the connectivity alru_cache and snapshot between tests."""
    clear_connectivity_caches()
    yield
    clear_connectivity_caches()


def build_checksum_write_body(
    task_name: str = "checksum-task",
    hostname: str = "host1",
    service_id: int = 1,
    **kwargs,
) -> dict:
    """Build a valid ChecksumTaskWrite-compatible request body."""
    return {
        "task_name": task_name,
        "hostname": hostname,
        "service_id": service_id,
        "recursion_method": "processlist",
        **kwargs,
    }


def build_fake_service(service_id: int = 1) -> dict:
    """Build a fake inventory service dict matching CreatedService shape."""
    return {
        "id": service_id,
        "name": "test-service",
        "type": ServiceTypeEnum.MYSQL.value,
        "port": 3306,
        "node_id": 1,
        "node": {
            "id": 1,
            "name": "test-node",
            "address": "127.0.0.1",
            "type": "generic",
        },
    }


class TestChecksumsListEndpoint:
    """Tests for GET /api/plugins/checksums/."""

    def test_checksums_list_returns_data(self, test_client, mock_task_api_dep):
        """Ensure the list endpoint returns task data."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [task], "total": 1, "offset": 0, "limit": 50},
                {
                    "items": [{"status": TaskHistoryStatusEnum.SUCCESS.value}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            ]
        )

        response = test_client.get("/api/plugins/checksums/")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == task["name"]
        assert data[0]["service_type"] == ServiceTypeEnum.MYSQL.value
        assert data[0]["status"] == TaskHistoryStatusEnum.SUCCESS.value

    def test_checksums_list_returns_empty_array(self, test_client, mock_task_api_dep):
        """Ensure the list endpoint returns an empty array when no tasks exist."""
        mock_task_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }

        response = test_client.get("/api/plugins/checksums/")

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []

    def test_checksums_list_returns_empty_for_non_mysql_service_type(
        self, test_client, mock_task_api_dep
    ):
        """Ensure non-MySQL service_type returns empty without calling the Tasks API."""
        response = test_client.get(
            "/api/plugins/checksums/",
            params={"service_type": ServiceTypeEnum.POSTGRESQL.value},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []
        mock_task_api_dep.get.assert_not_called()

    def test_checksums_list_filters_by_status(self, test_client, mock_task_api_dep):
        """Ensure the status filter is propagated correctly."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [task], "total": 1, "offset": 0, "limit": 50},
                {
                    "items": [{"status": TaskHistoryStatusEnum.RUNNING.value}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            ]
        )

        response = test_client.get(
            "/api/plugins/checksums/",
            params={
                "service_type": ServiceTypeEnum.MYSQL.value,
                "status": TaskHistoryStatusEnum.RUNNING.value,
            },
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == TaskHistoryStatusEnum.RUNNING.value
        assert mock_task_api_dep.get.call_args_list == [
            call("/", params={"owner": TaskOwner.CHECKSUMS.value}),
            call(f"/{task['name']}/history/"),
        ]

    def test_checksums_list_returns_422_for_invalid_service_type(
        self, test_client, mock_task_api_dep
    ):
        """Ensure an unrecognised service_type enum value is rejected with 422."""
        response = test_client.get(
            "/api/plugins/checksums/",
            params={"service_type": "not_a_valid_type"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.get.assert_not_called()

    def test_checksums_list_returns_422_for_invalid_status(
        self, test_client, mock_task_api_dep
    ):
        """Ensure an unrecognised status enum value is rejected with 422."""
        response = test_client.get(
            "/api/plugins/checksums/",
            params={"status": "not_a_valid_status"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.get.assert_not_called()

    def test_checksums_list_excludes_tasks_whose_status_does_not_match_filter(
        self, test_client, mock_task_api_dep
    ):
        """Ensure tasks with a status that does not match the filter are omitted."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [task], "total": 1, "offset": 0, "limit": 50},
                {
                    "items": [{"status": TaskHistoryStatusEnum.FAILED.value}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            ]
        )

        response = test_client.get(
            "/api/plugins/checksums/",
            params={"status": TaskHistoryStatusEnum.SUCCESS.value},
        )

        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


class TestChecksumsDetailEndpoint:
    """Tests for GET /api/plugins/checksums/{task_name}."""

    def test_checksums_detail_returns_task(self, test_client, mock_task_api_dep):
        """Ensure the detail endpoint returns a single task with correct fields."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {
                    "items": [{"status": TaskHistoryStatusEnum.FAILED.value}],
                    "total": 1,
                    "offset": 0,
                    "limit": 50,
                },
            ]
        )

        response = test_client.get(f"/api/plugins/checksums/{task['name']}")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == task["name"]
        assert body["service_type"] == ServiceTypeEnum.MYSQL.value
        assert body["status"] == TaskHistoryStatusEnum.FAILED.value

    def test_checksums_detail_returns_404_for_missing_task(
        self, test_client, mock_task_api_dep
    ):
        """Ensure the detail endpoint returns 404 when the task does not exist."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ) as mock_get:
            response = test_client.get("/api/plugins/checksums/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert response.json() == {"detail": "Not Found"}
        mock_get.assert_awaited_once_with("nonexistent", mock_task_api_dep)

    def test_checksums_detail_returns_404_for_wrong_owner(
        self, test_client, mock_task_api_dep
    ):
        """Ensure the detail endpoint returns 404 when the task owner is not checksums."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.get("/api/plugins/checksums/some-backup-task")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_checksums_detail_returns_null_status_when_task_has_no_history(
        self, test_client, mock_task_api_dep
    ):
        """Ensure the detail endpoint returns status=null when the task has no history entries."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )

        response = test_client.get(f"/api/plugins/checksums/{task['name']}")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["status"] is None

    def test_checksums_detail_does_not_fetch_history_when_task_not_found(
        self, test_client, mock_task_api_dep
    ):
        """Ensure the history call is never made when the task lookup raises 404."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.get("/api/plugins/checksums/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.get.assert_not_called()


class TestChecksumsSchemaEndpoint:
    """Tests for GET /api/plugins/checksums/schema."""

    def test_checksums_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with JSON content."""
        response = test_client.get("/api/plugins/checksums/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_checksums_schema_contains_plugin_name(self, test_client):
        """Ensure the schema body carries the correct plugin name."""
        response = test_client.get("/api/plugins/checksums/schema")

        assert response.json()["name"] == "checksums"

    def test_checksums_schema_contains_expected_fields(self, test_client):
        """Ensure the schema includes all expected form field names."""
        response = test_client.get("/api/plugins/checksums/schema")

        all_fields = [
            field for section in response.json()["forms"] for field in section["fields"]
        ]
        field_names = {f["name"] for f in all_fields}

        expected = {
            "task_name",
            "hostname",
            "service_id",
            "databases",
            "tables",
            "recursion_method",
            "dsn_table",
            "binary_index",
            "explain_arg",
            "fail_on_stopped_replication",
            "truncate_replicate_table",
            "pause_file",
            "progress",
            "set_vars",
            "max_load",
            "chunk_time",
            "max_lag",
        }
        assert expected.issubset(field_names)

    def test_checksums_schema_capabilities(self, test_client):
        """Ensure the schema declares the expected capabilities."""
        response = test_client.get("/api/plugins/checksums/schema")
        caps = response.json()["capabilities"]

        assert caps["chaining"] is True
        assert caps["alert_on_fail"] is True
        assert caps["scheduling"] is True


class TestChecksumsCreateEndpoint:
    """Tests for POST /api/plugins/checksums/."""

    def test_checksums_create_returns_201(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure creating a checksum task returns HTTP 201 with the task body."""
        task = build_checksum_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post("/api/plugins/checksums/", json=body)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["name"] == task["name"]
        assert data["service_type"] == ServiceTypeEnum.MYSQL.value

    def test_checksums_create_calls_tasks_api_with_correct_owner(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure the POST endpoint calls the Tasks API with owner=CHECKSUMS."""
        task = build_checksum_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(service_id=created_service.id)
        test_client.post("/api/plugins/checksums/", json=body)

        mock_task_api_dep.post.assert_awaited_once()
        _, call_kwargs = mock_task_api_dep.post.call_args
        assert call_kwargs["json"]["owner"] == TaskOwner.CHECKSUMS.value

    def test_checksums_create_returns_422_missing_required_fields(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when all required fields are absent."""
        response = test_client.post("/api/plugins/checksums/", json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_missing_task_name(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when task_name is absent."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"hostname": "host1", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_missing_hostname(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when hostname is absent."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": "my-task", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_missing_service_id(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when service_id is absent."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": "my-task", "hostname": "host1"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_404_when_service_not_found(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 404 when the inventory service does not exist."""
        mock_inventory_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        body = build_checksum_write_body(service_id=9999)
        response = test_client.post("/api/plugins/checksums/", json=body)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_dsn_recursion_expands_correctly(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure recursion_method=dsn with empty dsn_table expands to the default DSN table."""
        task = build_checksum_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(
            service_id=created_service.id,
            recursion_method="dsn",
            dsn_table="",
        )
        test_client.post("/api/plugins/checksums/", json=body)

        mock_task_api_dep.post.assert_awaited_once()
        _, call_kwargs = mock_task_api_dep.post.call_args
        args_str = call_kwargs["json"]["data"]["meta"]["args"]
        args = shlex.split(args_str)
        recursion_arg = next(
            (a for a in args if a.startswith("--recursion-method=")), None
        )
        assert recursion_arg is not None
        assert "dsn=" in recursion_arg
        assert "D=percona,t=dsns" in recursion_arg

    def test_checksums_create_dsn_recursion_uses_provided_dsn_table(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure a custom dsn_table is forwarded verbatim into the recursion arg."""
        task = build_checksum_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(
            service_id=created_service.id,
            recursion_method="dsn",
            dsn_table="D=mydb,t=custom_dsns",
        )
        test_client.post("/api/plugins/checksums/", json=body)

        _, call_kwargs = mock_task_api_dep.post.call_args
        args_str = call_kwargs["json"]["data"]["meta"]["args"]
        assert "D=mydb,t=custom_dsns" in args_str

    def test_checksums_create_returns_422_for_empty_task_name(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when task_name is an empty string (NonEmptyStr)."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": "", "hostname": "host1", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_for_empty_hostname(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when hostname is an empty string (NonEmptyStr)."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": "my-task", "hostname": "", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_for_null_task_name(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when task_name is JSON null."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": None, "hostname": "host1", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_for_null_hostname(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when hostname is JSON null."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": "my-task", "hostname": None, "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_returns_422_for_non_integer_service_id(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure POST returns 422 when service_id is not a number."""
        response = test_client.post(
            "/api/plugins/checksums/",
            json={"task_name": "my-task", "hostname": "host1", "service_id": "abc"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_checksums_create_propagates_tasks_api_error(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure POST propagates an error raised by the Tasks API."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(side_effect=HTTPNotFoundException())

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post("/api/plugins/checksums/", json=body)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.parametrize(
        "recursion_method", ["processlist", "hosts", "none", "default"]
    )
    def test_checksums_create_non_dsn_recursion_does_not_include_dsn_key(
        self,
        recursion_method,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        created_service,
    ):
        """Ensure non-DSN recursion methods are forwarded without dsn= expansion."""
        task = build_checksum_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(
            service_id=created_service.id,
            recursion_method=recursion_method,
        )
        test_client.post("/api/plugins/checksums/", json=body)

        _, call_kwargs = mock_task_api_dep.post.call_args
        args_str = call_kwargs["json"]["data"]["meta"]["args"]
        assert "dsn=" not in args_str

    def test_checksums_create_with_connectivity_check_failure_populates_warning(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Populate ``connectivity_warning`` when the connectivity check fails."""
        task = build_checksum_task(with_connectivity_meta=True)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(
            side_effect=[task, {"success": False, "error": "connection refused"}]
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post("/api/plugins/checksums/", json=body)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["connectivity_warning"] == {
            "target": "host1",
            "service_type": "mysql",
            "message": "connection refused",
        }
        assert get_latest_connectivity_result("host1", "mysql") is False

    def test_checksums_create_with_connectivity_check_success_warning_is_null(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Serialize ``connectivity_warning`` as ``null`` on success."""
        task = build_checksum_task(with_connectivity_meta=True)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(
            side_effect=[task, {"success": True, "error": None}]
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post("/api/plugins/checksums/", json=body)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert "connectivity_warning" in data
        assert data["connectivity_warning"] is None
        assert get_latest_connectivity_result("host1", "mysql") is True

    def test_checksums_create_with_meta_missing_connectivity_keys_warning_is_null(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Serialize ``connectivity_warning`` as ``null`` when meta lacks the keys."""
        task = build_checksum_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post("/api/plugins/checksums/", json=body)

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["connectivity_warning"] is None
        assert mock_task_api_dep.post.await_count == 1
        assert get_latest_connectivity_result("host1", "mysql") is None

    def test_checksums_create_opt_out_skips_connectivity_check(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Skip the connectivity check when ``check_connectivity=false``."""
        task = build_checksum_task(with_connectivity_meta=True)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post(
            "/api/plugins/checksums/",
            json=body,
            params={"check_connectivity": "false"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["connectivity_warning"] is None
        assert mock_task_api_dep.post.await_count == 1
        assert get_latest_connectivity_result("host1", "mysql") is None

    def test_checksums_create_opt_in_explicit_true_runs_check(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Run the check when ``check_connectivity=true`` is explicit."""
        task = build_checksum_task(with_connectivity_meta=True)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(
            side_effect=[task, {"success": True, "error": None}]
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.post(
            "/api/plugins/checksums/",
            json=body,
            params={"check_connectivity": "true"},
        )

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["connectivity_warning"] is None
        assert get_latest_connectivity_result("host1", "mysql") is True

    def test_checksums_create_invalid_check_connectivity_returns_422(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Reject unparseable ``check_connectivity`` values with HTTP 422."""
        body = build_checksum_write_body()
        response = test_client.post(
            "/api/plugins/checksums/",
            json=body,
            params={"check_connectivity": "garbage"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()


class TestChecksumsDeleteEndpoint:
    """Tests for DELETE /api/plugins/checksums/{task_name}."""

    def test_checksums_delete_returns_204(self, test_client, mock_task_api_dep):
        """Ensure deleting a checksum task returns HTTP 204 with an empty body."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.delete(f"/api/plugins/checksums/{task['name']}")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert response.content == b""

    def test_checksums_delete_calls_tasks_api_delete(
        self, test_client, mock_task_api_dep
    ):
        """Ensure DELETE calls the Tasks API with the correct task name path."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        test_client.delete(f"/api/plugins/checksums/{task['name']}")

        mock_task_api_dep.delete.assert_awaited_once_with(f"/{task['name']}")

    def test_checksums_delete_returns_404_for_missing_task(
        self, test_client, mock_task_api_dep
    ):
        """Ensure DELETE returns 404 when the task does not exist."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.delete("/api/plugins/checksums/nonexistent")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.delete.assert_not_called()

    def test_checksums_delete_returns_404_for_wrong_owner(
        self, test_client, mock_task_api_dep
    ):
        """Ensure DELETE returns 404 when the task is not owned by checksums."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.delete("/api/plugins/checksums/some-backup-task")

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_checksums_delete_propagates_tasks_api_delete_failure(
        self, test_client, mock_task_api_dep
    ):
        """Ensure DELETE propagates an error raised by the Tasks API delete call.

        The ownership check (tasks_api.get) succeeds, but the subsequent
        tasks_api.delete call fails — the error must propagate to the caller.
        """
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.delete = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.delete(f"/api/plugins/checksums/{task['name']}")

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.delete.assert_awaited_once_with(f"/{task['name']}")


class TestChecksumsExecuteEndpoint:
    """Tests for POST /api/plugins/checksums/{task_name}/execute."""

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_201_with_task_name_and_id(
        self, test_client, mock_task_api_dep
    ):
        """Ensure executing a checksum task returns 201 with task_name and task_id."""
        expected_task_id = 99
        task = build_checksum_task("my-task")
        mock_task_api_dep.get.return_value = task
        mock_task_api_dep.post.return_value = {"id": expected_task_id}

        response = test_client.post("/api/plugins/checksums/my-task/execute", json={})

        assert response.status_code == status.HTTP_201_CREATED
        data = response.json()
        assert data["task_name"] == "my-task"
        assert data["task_id"] == expected_task_id

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_404_for_unknown_task(self, test_client, mock_task_api_dep):
        """Ensure executing an unknown task name returns 404."""
        mock_task_api_dep.get.side_effect = HTTPNotFoundException()

        response = test_client.post(
            "/api/plugins/checksums/ghost-task/execute", json={}
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_execute_returns_409_when_task_already_running(
        self, test_client, mock_task_api_dep
    ):
        """Ensure executing a task that is already running returns 409."""
        task = build_checksum_task("busy-task")
        mock_task_api_dep.get.return_value = task

        def raise_conflict():
            raise HTTPConflictException("Task is already running or pending.")

        sep_app.dependency_overrides[check_for_conflicted_running_tasks] = (
            raise_conflict
        )
        try:
            response = test_client.post(
                "/api/plugins/checksums/busy-task/execute", json={}
            )
        finally:
            sep_app.dependency_overrides.pop(check_for_conflicted_running_tasks, None)

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_422_for_past_eta(self, test_client, mock_task_api_dep):
        """Ensure a past-dated eta is rejected with 422 by Pydantic validation."""
        task = build_checksum_task("my-task")
        mock_task_api_dep.get.return_value = task

        response = test_client.post(
            "/api/plugins/checksums/my-task/execute",
            json={"eta": "2000-01-01T00:00:00Z"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_forwards_only_provided_fields(
        self, test_client, mock_task_api_dep
    ):
        """Ensure only non-None fields are forwarded to the Tasks API execute call."""
        task = build_checksum_task("my-task")
        mock_task_api_dep.get.return_value = task
        mock_task_api_dep.post.return_value = {"id": 1}

        test_client.post(
            "/api/plugins/checksums/my-task/execute",
            json={"chain_on_failure": True},
        )

        mock_task_api_dep.post.assert_awaited_once_with(
            "/execute/my-task",
            json={"chain_on_failure": True},
        )

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_propagates_tasks_api_error(self, test_client, mock_task_api_dep):
        """Ensure errors raised by the Tasks API /execute call propagate to the caller."""
        task = build_checksum_task("my-task")
        mock_task_api_dep.get.return_value = task
        mock_task_api_dep.post.side_effect = HTTPBadGatewayException()

        response = test_client.post("/api/plugins/checksums/my-task/execute", json={})

        assert response.status_code == status.HTTP_502_BAD_GATEWAY

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_task_id_is_none_when_tasks_api_omits_id(
        self, test_client, mock_task_api_dep
    ):
        """Ensure task_id serializes as null when the Tasks API response has no 'id' key."""
        task = build_checksum_task("my-task")
        mock_task_api_dep.get.return_value = task
        mock_task_api_dep.post.return_value = {}

        response = test_client.post("/api/plugins/checksums/my-task/execute", json={})

        assert response.status_code == status.HTTP_201_CREATED
        assert response.json()["task_id"] is None

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_422_for_non_string_chain_task_names(
        self, test_client, mock_task_api_dep
    ):
        """Ensure chain_task_names containing non-string elements is rejected with 422."""
        task = build_checksum_task("my-task")
        mock_task_api_dep.get.return_value = task

        response = test_client.post(
            "/api/plugins/checksums/my-task/execute",
            json={"chain_task_names": [1, 2, 3]},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


class TestChecksumsUpdateEndpoint:
    """Tests for PUT /api/plugins/checksums/{task_name}."""

    def test_checksums_update_returns_200(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure updating a checksum task returns HTTP 200 with the task body."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.put = AsyncMock(return_value=task)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.put(f"/api/plugins/checksums/{task['name']}", json=body)

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["name"] == task["name"]
        assert data["service_type"] == ServiceTypeEnum.MYSQL.value

    def test_checksums_update_calls_tasks_api_put_with_path_task_name(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure PUT calls tasks_api.put with the path task name and correct owner."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.put = AsyncMock(return_value=task)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(service_id=created_service.id)
        test_client.put(f"/api/plugins/checksums/{task['name']}", json=body)

        mock_task_api_dep.put.assert_awaited_once()
        put_path, put_kwargs = mock_task_api_dep.put.call_args
        assert put_path == (f"/{task['name']}",)
        assert put_kwargs["json"]["owner"] == TaskOwner.CHECKSUMS.value

    def test_checksums_update_rename_uses_path_task_name_in_put_url(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure the PUT URL uses the path task name even when body contains a new name."""
        old_name = "old-task-name"
        new_name = "new-task-name"
        task = build_checksum_task(old_name)
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.put = AsyncMock(return_value=task)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(
            task_name=new_name, service_id=created_service.id
        )
        test_client.put(f"/api/plugins/checksums/{old_name}", json=body)

        put_path, put_kwargs = mock_task_api_dep.put.call_args
        assert put_path == (f"/{old_name}",)
        assert put_kwargs["json"]["name"] == new_name

    def test_checksums_update_returns_404_for_missing_task(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 404 when the task does not exist."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            body = build_checksum_write_body()
            response = test_client.put("/api/plugins/checksums/nonexistent", json=body)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_404_for_wrong_owner(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 404 when the task is not owned by checksums."""
        with patch(
            "app.sep.plugins.checksums.api_routes.get_checksums_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            body = build_checksum_write_body()
            response = test_client.put(
                "/api/plugins/checksums/some-backup-task", json=body
            )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_404_when_service_not_found(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 404 when the inventory service does not exist."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_inventory_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        body = build_checksum_write_body(service_id=9999)
        response = test_client.put(f"/api/plugins/checksums/{task['name']}", json=body)

        assert response.status_code == status.HTTP_404_NOT_FOUND
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_409_for_protected_task(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure PUT returns 409 without calling the Tasks API when task is protected."""
        task = build_checksum_task()
        task["protected"] = True
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.put(f"/api/plugins/checksums/{task['name']}", json=body)

        assert response.status_code == status.HTTP_409_CONFLICT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_missing_required_fields(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when all required fields are absent.

        The ChecksumsTask dep resolves before body validation, so a valid task
        response is needed in the mock to let Pydantic body validation win.
        """
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put("/api/plugins/checksums/some-task", json={})

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_missing_task_name(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when task_name is absent."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json={"hostname": "host1", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_missing_hostname(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when hostname is absent."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json={"task_name": "some-task", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_missing_service_id(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when service_id is absent."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json={"task_name": "some-task", "hostname": "host1"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_for_empty_task_name(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when task_name is an empty string."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json={"task_name": "", "hostname": "host1", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_for_empty_hostname(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when hostname is an empty string."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json={"task_name": "some-task", "hostname": "", "service_id": 1},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_for_non_integer_service_id(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Ensure PUT returns 422 when service_id is not a number."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json={"task_name": "some-task", "hostname": "host1", "service_id": "abc"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_returns_422_for_invalid_check_connectivity(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ):
        """Reject unparseable check_connectivity values with HTTP 422."""
        mock_task_api_dep.get = AsyncMock(return_value=build_checksum_task("some-task"))

        body = build_checksum_write_body()
        response = test_client.put(
            "/api/plugins/checksums/some-task",
            json=body,
            params={"check_connectivity": "garbage"},
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.put.assert_not_called()

    def test_checksums_update_opt_out_skips_connectivity_check(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Skip the connectivity check when check_connectivity=false."""
        task = build_checksum_task(with_connectivity_meta=True)
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.put = AsyncMock(return_value=task)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.put(
            f"/api/plugins/checksums/{task['name']}",
            json=body,
            params={"check_connectivity": "false"},
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["connectivity_warning"] is None
        assert mock_task_api_dep.put.await_count == 1
        assert get_latest_connectivity_result("host1", "mysql") is None

    def test_checksums_update_with_connectivity_check_failure_populates_warning(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Populate connectivity_warning when the connectivity check fails."""
        task = build_checksum_task(with_connectivity_meta=True)
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.put = AsyncMock(return_value=task)
        mock_task_api_dep.post = AsyncMock(
            return_value={"success": False, "error": "connection refused"}
        )
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.put(
            f"/api/plugins/checksums/{task['name']}",
            json=body,
        )

        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["connectivity_warning"] == {
            "target": "host1",
            "service_type": "mysql",
            "message": "connection refused",
        }
        assert get_latest_connectivity_result("host1", "mysql") is False

    def test_checksums_update_propagates_tasks_api_error(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Ensure errors raised by tasks_api.put propagate to the caller."""
        task = build_checksum_task()
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.put = AsyncMock(side_effect=HTTPNotFoundException())
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )

        body = build_checksum_write_body(service_id=created_service.id)
        response = test_client.put(f"/api/plugins/checksums/{task['name']}", json=body)

        assert response.status_code == status.HTTP_404_NOT_FOUND

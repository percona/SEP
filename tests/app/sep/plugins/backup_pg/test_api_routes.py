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

"""Tests for the backup_pg plugin JSON API routes under /api/plugins/backup_pg/."""

from typing import Any
from unittest.mock import AsyncMock, call

import pytest
import yaml
from fastapi import HTTPException, status

from app.core.db.crud import DEFAULT_PAGINATION_LIMIT, MAX_PAGINATION_LIMIT
from app.core.exceptions import HTTPNotFoundException
from app.inventory.models import ServiceTypeEnum
from app.sep.connectivity import CONNECTIVITY_META_PORT_KEY
from app.sep.inventory import CreatedNode, CreatedService
from app.sep.plugins.backup_pg.models import BackupType
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner
from tests.app.factories import CreatedServiceFactory, TaskFactory

API_BASE = "/api/plugins/backup_pg"
THREE_PARENT_FIXTURE_TOTAL = 3
BEARER_HEADERS = {"Authorization": "Bearer test-token"}

FIXTURE_PG_HOST = "localhost"
FIXTURE_PG_PORT = 5432


def build_backup_task(name: str = "pg-backup-task", **overrides: Any) -> dict:
    """Build a fake backup_pg task payload for route tests."""
    data_overrides = overrides.pop("data", {})
    config = yaml.dump(
        {
            "SERVER_LIST": [
                {
                    "HOST": "localhost",
                    "PORT": 5432,
                    "BACKUP_TYPE": BackupType.PGBACKREST.value,
                }
            ],
            "ALL_SERVERS": {},
        }
    )
    task = TaskFactory.build(
        name=name,
        owner=TaskOwner.BACKUP_PG,
        backend=TaskBackendEnum.PROXY,
        **overrides,
    )
    payload = task.model_dump(mode="json")
    payload["data"] = {
        "task": "run-python",
        "meta": {
            "target": "pg-host",
            "config": config,
            "requirements": "packaging\nPyYAML",
        },
        "payload": "file:///plugins/backup_pg/payload",
        **data_overrides,
    }
    return payload


def build_backup_write_body(
    task_name: str = "pg-backup-task",
    hostname: str = "pg-host",
    service_id: int = 1,
    backup_dir: str = "/var/lib/pgbackrest",
    **kwargs: Any,
) -> dict:
    """Build a valid BackupTaskWrite-compatible request body."""
    return {
        "task_name": task_name,
        "hostname": hostname,
        "service_id": service_id,
        "backup_dir": backup_dir,
        "pgbackrest_backup_type": "incr",
        **kwargs,
    }


def build_execute_response(
    task_id: int | None = 99, task_name: str = "pg-backup-task"
) -> dict:
    """Build a minimal TaskHistoryResponse-shaped dict for execute endpoint tests."""
    return {
        "id": task_id,
        "execution_request": {"task": task_name, "target": "pg-host"},
        "task": {**build_backup_task(task_name), "deleted_at": None},
    }


def mock_task_api_get_by_path(tasks_by_path: dict[str, Any]) -> AsyncMock:
    """Return a path-keyed ``tasks_api.get`` mock safe for parallel fetches."""

    async def _mock_get(path: str, **kwargs: Any) -> Any:
        if path.endswith("/history/"):
            return {"items": []}
        if path == "/":
            return {"items": list(tasks_by_path.values()), "total": len(tasks_by_path)}
        if path in tasks_by_path:
            return tasks_by_path[path]
        raise AssertionError(f"Unexpected tasks_api.get path: {path!r}")

    return AsyncMock(side_effect=_mock_get)


@pytest.fixture
def pg_service(created_node: CreatedNode) -> CreatedService:
    """Return a fake created PostgreSQL service."""
    return CreatedServiceFactory.build(
        node=created_node, type=ServiceTypeEnum.POSTGRESQL
    )


class TestBackupPgPluginSchemaEndpoint:
    """Tests for GET /api/plugins/backup_pg/schema."""

    def test_schema_returns_200(self, test_client) -> None:
        """Schema endpoint returns HTTP 200 with JSON content."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]
        body = response.json()
        assert body["name"] == "backup_pg"

    def test_schema_has_no_derived_cascade(self, test_client) -> None:
        """Schema does not declare DerivedTask cascade (INCR/DIFF is config-driven)."""
        response = test_client.get(f"{API_BASE}/schema")

        body = response.json()
        assert not body.get("derived")


class TestBackupPgApiList:
    """Tests for GET /api/plugins/backup_pg/."""

    def test_list_returns_200(self, test_client, mock_task_api_dep) -> None:
        """List returns 200 with paginated items."""
        parent = build_backup_task("pg-backup-a")
        mock_task_api_dep.get = AsyncMock(return_value={"items": [parent], "total": 1})

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == 1
        assert body["offset"] == 0
        assert body["limit"] == DEFAULT_PAGINATION_LIMIT
        assert len(body["items"]) == 1
        assert body["items"][0]["name"] == "pg-backup-a"
        mock_task_api_dep.get.assert_any_await(
            "/",
            params={
                "owner": TaskOwner.BACKUP_PG.value,
                "offset": 0,
                "limit": DEFAULT_PAGINATION_LIMIT,
            },
        )

    def test_list_returns_empty_page(self, test_client, mock_task_api_dep) -> None:
        """List returns 200 with empty items when no tasks exist."""
        mock_task_api_dep.get = AsyncMock(return_value={"items": [], "total": 0})

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["items"] == []
        assert body["total"] == 0

    def test_list_forwards_offset_and_limit_to_tasks_api(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Forward ``offset`` and ``limit`` to the Tasks API for server-side pagination."""
        task_b = build_backup_task("pg-backup-b")
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [task_b], "total": THREE_PARENT_FIXTURE_TOTAL}
        )

        response = test_client.get(f"{API_BASE}/?offset=1&limit=1")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["total"] == THREE_PARENT_FIXTURE_TOTAL
        assert body["offset"] == 1
        assert body["limit"] == 1
        assert [item["name"] for item in body["items"]] == ["pg-backup-b"]
        mock_task_api_dep.get.assert_any_await(
            "/",
            params={
                "owner": TaskOwner.BACKUP_PG.value,
                "offset": 1,
                "limit": 1,
            },
        )

    def test_list_rejects_limit_above_cap(self, test_client, mock_task_api_dep) -> None:
        """Reject limit above MAX_PAGINATION_LIMIT with 422 to block pagination DoS."""
        response = test_client.get(f"{API_BASE}/?limit={MAX_PAGINATION_LIMIT + 1}")

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_list_tolerates_history_fetch_failure(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Return 200 when one history fetch fails after the task list."""
        task_a = build_backup_task("pg-backup-a")
        task_b = build_backup_task("pg-backup-b")

        async def _mock_get(path: str, **kwargs: Any) -> Any:
            if path == "/":
                return {"items": [task_a, task_b], "total": 2}
            if path == "/pg-backup-a/history/":
                return {"items": [{"status": "success"}]}
            if path == "/pg-backup-b/history/":
                raise HTTPNotFoundException
            raise AssertionError(f"Unexpected tasks_api.get path: {path!r}")

        mock_task_api_dep.get = AsyncMock(side_effect=_mock_get)

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        by_name = {item["name"]: item for item in response.json()["items"]}
        assert by_name["pg-backup-a"]["status"] == TaskHistoryStatusEnum.SUCCESS.value
        assert by_name["pg-backup-b"]["status"] is None


class TestBackupPgApiDetail:
    """Tests for GET /api/plugins/backup_pg/{task_name}."""

    def test_detail_returns_200(self, test_client, mock_task_api_dep) -> None:
        """Detail returns 200 with the requested task and Jinja-parity host/port."""
        task = build_backup_task("pg-backup-task")
        mock_task_api_dep.get = mock_task_api_get_by_path({"/pg-backup-task": task})

        response = test_client.get(f"{API_BASE}/pg-backup-task")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "pg-backup-task"
        assert body["owner"] == TaskOwner.BACKUP_PG.value
        assert body["host"] == FIXTURE_PG_HOST
        assert body["port"] == FIXTURE_PG_PORT

    def test_detail_port_falls_back_to_meta_when_yaml_omits_port(
        self, test_client, mock_task_api_dep
    ) -> None:
        """PORT missing from YAML surfaces the resolved meta connectivity port."""
        meta_port = 6543
        config = yaml.dump(
            {
                "SERVER_LIST": [
                    {
                        "HOST": "localhost",
                        "BACKUP_TYPE": BackupType.PGBACKREST.value,
                    }
                ],
                "ALL_SERVERS": {},
            }
        )
        task = build_backup_task(
            "pg-backup-task",
            data={
                "meta": {
                    "target": "pg-host",
                    "config": config,
                    "requirements": "packaging\nPyYAML",
                    CONNECTIVITY_META_PORT_KEY: meta_port,
                }
            },
        )
        mock_task_api_dep.get = mock_task_api_get_by_path({"/pg-backup-task": task})

        response = test_client.get(f"{API_BASE}/pg-backup-task")

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["port"] == meta_port

    def test_detail_returns_404_for_unknown_task(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Detail returns 404 when the task cannot be resolved."""
        mock_task_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.get(f"{API_BASE}/ghost-task")

        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestBackupPgApiCreate:
    """Tests for POST /api/plugins/backup_pg/."""

    @pytest.mark.usefixtures("_mock_check_create_has_no_conflicted_running_tasks")
    def test_create_returns_201_and_posts_task(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        pg_service: CreatedService,
    ) -> None:
        """POST creates a single task via cascade_create_tasks with empty derived list."""
        mock_inventory_api_dep.get = AsyncMock(return_value=pg_service.model_dump())
        created_task = build_backup_task("pg-backup-task")
        mock_task_api_dep.post = AsyncMock(return_value=created_task)
        mock_task_api_dep.get = mock_task_api_get_by_path(
            {"/pg-backup-task": created_task}
        )

        response = test_client.post(
            f"{API_BASE}/",
            json=build_backup_write_body(service_id=pg_service.id),
            headers=BEARER_HEADERS,
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["name"] == "pg-backup-task"
        assert mock_task_api_dep.post.await_count == 1
        first_post = mock_task_api_dep.post.await_args_list[0].kwargs["json"]
        assert first_post["owner"] == TaskOwner.BACKUP_PG.value
        assert first_post["name"] == "pg-backup-task"

    def test_create_returns_422_on_invalid_payload(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ) -> None:
        """POST returns 422 when required fields are missing."""
        response = test_client.post(
            f"{API_BASE}/", json={"task_name": "only-name"}, headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    def test_create_returns_422_on_unknown_backup_type(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ) -> None:
        """POST returns 422 when pgbackrest_backup_type is outside INCR/DIFF."""
        response = test_client.post(
            f"{API_BASE}/",
            json=build_backup_write_body(pgbackrest_backup_type="full"),
            headers=BEARER_HEADERS,
        )

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    @pytest.mark.usefixtures("_mock_check_create_has_no_conflicted_running_tasks")
    def test_create_rolls_back_on_post_failure(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        pg_service: CreatedService,
    ) -> None:
        """When the parent POST fails, cascade does not attempt further work."""
        mock_inventory_api_dep.get = AsyncMock(return_value=pg_service.model_dump())
        mock_task_api_dep.post = AsyncMock(
            side_effect=HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        )
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.post(
            f"{API_BASE}/",
            json=build_backup_write_body(service_id=pg_service.id),
            headers=BEARER_HEADERS,
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        # parent POST failed before adding to created_names → no rollback DELETE
        assert mock_task_api_dep.delete.await_args_list == []

    @pytest.mark.usefixtures(
        "_mock_check_create_has_no_conflicted_running_tasks_raises"
    )
    def test_create_returns_409_when_task_already_running(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        pg_service: CreatedService,
    ) -> None:
        """POST returns 409 when an in-flight task with the same name exists.

        The body-aware conflict guard short-circuits before
        ``cascade_create_tasks`` is reached, so no upstream POST is issued.
        """
        mock_inventory_api_dep.get = AsyncMock(return_value=pg_service.model_dump())
        mock_task_api_dep.post = AsyncMock()

        response = test_client.post(
            f"{API_BASE}/",
            json=build_backup_write_body(service_id=pg_service.id),
            headers=BEARER_HEADERS,
        )

        assert response.status_code == status.HTTP_409_CONFLICT
        assert mock_task_api_dep.post.await_count == 0

    def test_create_returns_422_when_backup_dir_missing(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep
    ) -> None:
        """POST returns 422 when the now-required ``backup_dir`` is omitted."""
        body = build_backup_write_body()
        del body["backup_dir"]

        response = test_client.post(f"{API_BASE}/", json=body, headers=BEARER_HEADERS)

        assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


class TestBackupPgApiDelete:
    """Tests for DELETE /api/plugins/backup_pg/{task_name}."""

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_delete_returns_204(self, test_client, mock_task_api_dep) -> None:
        """DELETE removes the task and returns 204."""
        task = build_backup_task("pg-backup-task")
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.delete(
            f"{API_BASE}/pg-backup-task", headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_task_api_dep.delete.await_args_list == [call("/pg-backup-task")]

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_delete_returns_404_for_unknown_task(
        self, test_client, mock_task_api_dep
    ) -> None:
        """DELETE returns 404 when the task is not found."""
        mock_task_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.delete(f"{API_BASE}/ghost-task", headers=BEARER_HEADERS)

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_delete_returns_500_when_cascade_partially_fails(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Return 500 when the cascade DELETE collects a non-404 failure."""
        task = build_backup_task("pg-backup-task")
        mock_task_api_dep.get = AsyncMock(return_value=task)
        derived_exc = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
        mock_task_api_dep.delete = AsyncMock(side_effect=derived_exc)

        response = test_client.delete(
            f"{API_BASE}/pg-backup-task", headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "pg-backup-task" in response.json()["detail"]

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks_raises")
    def test_delete_returns_409_when_task_running(
        self, test_client, mock_task_api_dep
    ) -> None:
        """DELETE returns 409 when a conflicting task is currently running."""
        response = test_client.delete(
            f"{API_BASE}/pg-backup-task", headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_409_CONFLICT


class TestBackupPgApiExecute:
    """Tests for POST /api/plugins/backup_pg/{task_name}/execute."""

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_201_with_task_name_and_id(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Executing a backup task returns 201 with task_name and task_id."""
        expected_task_id = 42
        task = build_backup_task("pg-backup-task")
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.post = AsyncMock(
            return_value=build_execute_response(expected_task_id)
        )

        response = test_client.post(
            f"{API_BASE}/pg-backup-task/execute", json={}, headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_201_CREATED
        body = response.json()
        assert body["task_name"] == "pg-backup-task"
        assert body["task_id"] == expected_task_id
        mock_task_api_dep.post.assert_awaited_once_with(
            "/execute/pg-backup-task", json={}
        )

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_returns_404_for_unknown_task(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Executing an unknown task returns 404."""
        mock_task_api_dep.get = AsyncMock(side_effect=HTTPNotFoundException())

        response = test_client.post(
            f"{API_BASE}/ghost-task/execute", json={}, headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks_raises")
    def test_execute_returns_409_when_already_running(
        self, test_client, mock_task_api_dep
    ) -> None:
        """Executing a task that is already running returns 409."""
        response = test_client.post(
            f"{API_BASE}/pg-backup-task/execute", json={}, headers=BEARER_HEADERS
        )

        assert response.status_code == status.HTTP_409_CONFLICT

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_serializes_eta_as_iso_string(
        self, test_client, mock_task_api_dep
    ) -> None:
        """``eta`` is serialized as an ISO string before being forwarded as JSON."""
        from datetime import datetime, timedelta, UTC

        eta = datetime.now(tz=UTC) + timedelta(hours=1)
        task = build_backup_task("pg-backup-task")
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.post = AsyncMock(return_value=build_execute_response())

        response = test_client.post(
            f"{API_BASE}/pg-backup-task/execute",
            json={"eta": eta.isoformat()},
            headers=BEARER_HEADERS,
        )

        assert response.status_code == status.HTTP_201_CREATED
        forwarded = mock_task_api_dep.post.await_args_list[0].kwargs["json"]
        assert isinstance(forwarded["eta"], str)
        # ISO round-trips back to an aware datetime
        assert datetime.fromisoformat(forwarded["eta"]).tzinfo is not None

    @pytest.mark.usefixtures("_mock_check_for_conflicted_running_tasks")
    def test_execute_drops_past_eta(self, test_client, mock_task_api_dep) -> None:
        """A past ``eta`` is dropped from the upstream payload (runs immediately)."""
        from datetime import datetime, timedelta, UTC

        eta = datetime.now(tz=UTC) - timedelta(hours=1)
        task = build_backup_task("pg-backup-task")
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.post = AsyncMock(return_value=build_execute_response())

        response = test_client.post(
            f"{API_BASE}/pg-backup-task/execute",
            json={"eta": eta.isoformat()},
            headers=BEARER_HEADERS,
        )

        assert response.status_code == status.HTTP_201_CREATED
        forwarded = mock_task_api_dep.post.await_args_list[0].kwargs["json"]
        assert "eta" not in forwarded


class TestBackupPgApiAuth:
    """Tests for API authentication."""

    def test_unauthenticated_list_returns_401(self, unauthenticated_client) -> None:
        """Reject unauthenticated access to the backup_pg API."""
        response = unauthenticated_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    @pytest.mark.parametrize(
        ("method", "path", "json_body"),
        [
            ("POST", f"{API_BASE}/", build_backup_write_body()),
            ("DELETE", f"{API_BASE}/pg-backup-task", None),
            ("POST", f"{API_BASE}/pg-backup-task/execute", {}),
        ],
        ids=["create", "delete", "execute"],
    )
    def test_mutation_without_bearer_returns_401(
        self,
        api_admin_client_no_bearer,
        method: str,
        path: str,
        json_body: dict | None,
    ) -> None:
        """Cookie-authenticated mutations without a Bearer header are rejected.

        Mutations must require ``Authorization: Bearer`` so cookie-bound
        cross-site JSON requests cannot bypass CSRF protection.
        """
        kwargs = {"json": json_body} if json_body is not None else {}
        response = api_admin_client_no_bearer.request(method, path, **kwargs)

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

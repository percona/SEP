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

"""Tests for the mysql_backups plugin JSON API routes."""

from datetime import datetime, UTC
from unittest.mock import AsyncMock, patch

import yaml
from fastapi import status

from app.core.exceptions import HTTPNotFoundException
from app.sep.plugins.mysql_backups.models import BackupType
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner

BEARER_HEADERS = {"Authorization": "Bearer test-token"}


def build_backup_task(
    name: str = "backup-task", backup_type: BackupType = BackupType.MYDUMPER
) -> dict:
    """Build a fake backups task payload for route tests."""
    config = yaml.dump(
        {
            "ALL_SERVERS": {"compress": False},
            "SERVER_LIST": [
                {
                    "ALIAS": "node1",
                    "HOST": "localhost",
                    "PORT": 3306,
                    "BACKUP_TYPE": backup_type.value,
                    "UPLOAD": [],
                }
            ],
        }
    )
    return {
        "id": 1,
        "name": name,
        "backend": TaskBackendEnum.PROXY,
        "owner": TaskOwner.BACKUPS,
        "is_template": False,
        "protected": False,
        "alert_on_fail": False,
        "data": {
            "task": "run-python",
            "meta": {
                "target": "host1",
                "config": config,
                "_service_name": "svc",
            },
            "payload": "file:///dev/null",
        },
        "created_at": datetime.now(UTC),
        "updated_at": None,
        "created_by": "user@example.com",
        "last_updated_by": "user@example.com",
    }


def build_backup_write_body(
    task_name: str = "backup-task",
    hostname: str = "host1",
    service_id: int = 1,
    backup_type: BackupType = BackupType.MYDUMPER,
    **kwargs,
) -> dict:
    """Build a valid backup-create JSON body."""
    return {
        "task_name": task_name,
        "hostname": hostname,
        "service_id": service_id,
        "backup_type": backup_type.value,
        **kwargs,
    }


class TestSchemaEndpoint:
    """Tests for GET /api/plugins/mysql_backups/schema."""

    def test_schema_returns_200(self, test_client):
        """The schema endpoint returns 200 and JSON content."""
        response = test_client.get("/api/plugins/mysql_backups/schema")
        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_schema_contains_plugin_name(self, test_client):
        """Body carries the plugin name."""
        response = test_client.get("/api/plugins/mysql_backups/schema")
        assert response.json()["name"] == "mysql_backups"

    def test_schema_capabilities(self, test_client):
        """Capabilities mirror Jinja2: chaining + alerts + scheduling."""
        caps = test_client.get("/api/plugins/mysql_backups/schema").json()[
            "capabilities"
        ]
        assert caps == {"chaining": True, "alert_on_fail": True, "scheduling": True}

    def test_schema_includes_backup_type_field(self, test_client):
        """The mode-discriminator field is present."""
        body = test_client.get("/api/plugins/mysql_backups/schema").json()
        names = {f["name"] for s in body["forms"] for f in s["fields"]}
        assert "backup_type" in names
        assert "upload" in names

    def test_schema_anonymous_returns_401(self, unauthenticated_client):
        """Anonymous schema fetch is rejected by IsApiAuthenticated."""
        response = unauthenticated_client.get("/api/plugins/mysql_backups/schema")
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


class TestListEndpoint:
    """Tests for GET /api/plugins/mysql_backups/."""

    def test_list_returns_data(self, test_client, mock_task_api_dep):
        """The list endpoint returns the registered backups tasks."""
        task = build_backup_task()
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
        response = test_client.get("/api/plugins/mysql_backups/")
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == task["name"]
        assert data[0]["status"] == TaskHistoryStatusEnum.SUCCESS.value
        assert data[0]["backup_type"] == BackupType.MYDUMPER.value

    def test_list_returns_empty(self, test_client, mock_task_api_dep):
        """Empty backup list returns an empty array."""
        mock_task_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/plugins/mysql_backups/")
        assert response.status_code == status.HTTP_200_OK
        assert response.json() == []


class TestDetailEndpoint:
    """Tests for GET /api/plugins/mysql_backups/{task_name}."""

    def test_detail_returns_task(self, test_client, mock_task_api_dep):
        """The detail endpoint returns a single backup task."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                task,
                {"items": [], "total": 0, "offset": 0, "limit": 50},
            ]
        )
        response = test_client.get(f"/api/plugins/mysql_backups/{task['name']}")
        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == task["name"]
        assert body["backup_type"] == BackupType.MYDUMPER.value

    def test_detail_returns_404_for_missing(self, test_client, mock_task_api_dep):
        """Missing task returns 404."""
        with patch(
            "app.sep.plugins.mysql_backups.api_routes.get_backups_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.get("/api/plugins/mysql_backups/nope")
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_detail_returns_404_for_wrong_owner(self, test_client, mock_task_api_dep):
        """Task owned by another plugin returns 404 (no cross-plugin enumeration)."""
        with patch(
            "app.sep.plugins.mysql_backups.api_routes.get_backups_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.get("/api/plugins/mysql_backups/some-checksums-task")
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestCreateEndpoint:
    """Tests for POST /api/plugins/mysql_backups/."""

    def test_create_returns_201(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """Happy path: backup_type=M creates a task with 201."""
        task = build_backup_task()
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)
        body = build_backup_write_body(
            service_id=created_service.id, backup_type=BackupType.MYDUMPER
        )
        response = test_client.post(
            "/api/plugins/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        assert response.json()["name"] == task["name"]

    def test_create_xtrabackup_happy_path(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """backup_type=X with xtrabackup field creates a task."""
        task = build_backup_task(backup_type=BackupType.XTRABACKUP)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.XTRABACKUP,
            xtrabackup_extra_args="--no-version-check",
        )
        response = test_client.post(
            "/api/plugins/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_binlog_happy_path(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """backup_type=B with binlog field creates a task."""
        task = build_backup_task(backup_type=BackupType.BINLOG)
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        mock_task_api_dep.post = AsyncMock(return_value=task)
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.BINLOG,
            binlog_prefix="bp",
        )
        response = test_client.post(
            "/api/plugins/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_201_CREATED

    def test_create_rejects_cross_mode_field(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """backup_type=M + xtrabackup_extra_args is rejected with 422."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(
            service_id=created_service.id,
            backup_type=BackupType.MYDUMPER,
            xtrabackup_extra_args="--foo",
        )
        response = test_client.post(
            "/api/plugins/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_rejects_recipient_without_encrypt(
        self, test_client, mock_task_api_dep, mock_inventory_api_dep, created_service
    ):
        """encryption_recipient without encrypt=True is rejected with 422."""
        mock_inventory_api_dep.get = AsyncMock(
            return_value=created_service.model_dump()
        )
        body = build_backup_write_body(
            service_id=created_service.id,
            encryption_recipient="ops@example.com",
        )
        response = test_client.post(
            "/api/plugins/mysql_backups/", json=body, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_rejects_missing_required_fields(
        self, test_client, mock_task_api_dep
    ):
        """Empty body returns 422 (required fields missing)."""
        response = test_client.post(
            "/api/plugins/mysql_backups/", json={}, headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
        mock_task_api_dep.post.assert_not_called()

    def test_create_anonymous_returns_401(
        self, unauthenticated_client, mock_task_api_dep
    ):
        """Anonymous create is rejected by IsApiAuthenticated."""
        body = build_backup_write_body()
        response = unauthenticated_client.post("/api/plugins/mysql_backups/", json=body)
        assert response.status_code in (
            status.HTTP_401_UNAUTHORIZED,
            status.HTTP_403_FORBIDDEN,
        )


class TestDeleteEndpoint:
    """Tests for DELETE /api/plugins/mysql_backups/{task_name}."""

    def test_delete_returns_204(self, test_client, mock_task_api_dep):
        """Successful delete returns 204."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(return_value=task)
        mock_task_api_dep.delete = AsyncMock()
        response = test_client.delete(
            f"/api/plugins/mysql_backups/{task['name']}", headers=BEARER_HEADERS
        )
        assert response.status_code == status.HTTP_204_NO_CONTENT
        mock_task_api_dep.delete.assert_awaited_once_with(f"/{task['name']}")

    def test_delete_returns_404_for_missing(self, test_client, mock_task_api_dep):
        """Delete of unknown task returns 404."""
        with patch(
            "app.sep.plugins.mysql_backups.api_routes.get_backups_task",
            new=AsyncMock(side_effect=HTTPNotFoundException()),
        ):
            response = test_client.delete(
                "/api/plugins/mysql_backups/nope", headers=BEARER_HEADERS
            )
        assert response.status_code == status.HTTP_404_NOT_FOUND


class TestExecuteEndpoint:
    """Tests for POST /api/plugins/mysql_backups/{task_name}/execute."""

    def _execute_response(self, task_id: int = 99) -> dict:
        return {
            "id": task_id,
            "execution_request": {"task": "run-python", "target": "host1"},
            "task": {**build_backup_task(), "deleted_at": None},
        }

    def test_execute_returns_201(self, test_client, mock_task_api_dep):
        """Happy path: execute returns 201 with task_id."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},  # running
                {"items": [], "total": 0, "offset": 0, "limit": 50},  # pending
                task,  # get_backups_task
            ]
        )
        mock_task_api_dep.post = AsyncMock(return_value=self._execute_response())
        response = test_client.post(
            f"/api/plugins/mysql_backups/{task['name']}/execute",
            json={},
            headers=BEARER_HEADERS,
        )
        assert response.status_code == status.HTTP_201_CREATED, response.text
        body = response.json()
        assert body["task_name"] == task["name"]
        assert body["task_id"] == 99  # noqa: PLR2004

    def test_execute_with_chain(self, test_client, mock_task_api_dep):
        """Chain args propagate to the Tasks API."""
        task = build_backup_task()
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                task,
            ]
        )
        mock_task_api_dep.post = AsyncMock(return_value=self._execute_response())
        response = test_client.post(
            f"/api/plugins/mysql_backups/{task['name']}/execute",
            json={
                "chain_task_names": ["other-task"],
                "chain_on_failure": True,
            },
            headers=BEARER_HEADERS,
        )
        assert response.status_code == status.HTTP_201_CREATED
        _, kwargs = mock_task_api_dep.post.call_args
        assert kwargs["json"] == {
            "chain_task_names": ["other-task"],
            "chain_on_failure": True,
        }

    def test_execute_returns_404_for_missing(self, test_client, mock_task_api_dep):
        """Execute against an unknown task returns 404."""
        # 1, 2: HasNoConflictedRunningTasks (running, pending histories).
        # 3: get_backups_task fetches the task; unparseable response → 404
        #    via the same ValidationError → HTTPNotFoundException path used
        #    by the detail endpoint tests.
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {"items": [], "total": 0, "offset": 0, "limit": 50},
                {},
            ]
        )
        response = test_client.post(
            "/api/plugins/mysql_backups/nope/execute",
            json={},
            headers=BEARER_HEADERS,
        )
        assert response.status_code == status.HTTP_404_NOT_FOUND

    def test_execute_with_cookie_only_returns_401(self, test_client, mock_task_api_dep):
        """Execute without Bearer header is rejected as 401."""
        response = test_client.post(
            "/api/plugins/mysql_backups/some-task/execute", json={}
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_task_api_dep.post.assert_not_called()


class TestBearerAuthGate:
    """Mutations must include an ``Authorization: Bearer`` header."""

    def test_create_with_cookie_only_returns_401(self, test_client, mock_task_api_dep):
        """POST without Bearer header is rejected as 401."""
        body = build_backup_write_body()
        response = test_client.post("/api/plugins/mysql_backups/", json=body)
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_task_api_dep.post.assert_not_called()

    def test_delete_with_cookie_only_returns_401(self, test_client, mock_task_api_dep):
        """DELETE without Bearer header is rejected as 401."""
        response = test_client.delete("/api/plugins/mysql_backups/some-task")
        assert response.status_code == status.HTTP_401_UNAUTHORIZED
        mock_task_api_dep.delete.assert_not_called()

    def test_list_with_cookie_only_returns_200(self, test_client, mock_task_api_dep):
        """Read endpoints still accept cookie-only auth."""
        mock_task_api_dep.get.return_value = {
            "items": [],
            "total": 0,
            "offset": 0,
            "limit": 50,
        }
        response = test_client.get("/api/plugins/mysql_backups/")
        assert response.status_code == status.HTTP_200_OK

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

"""Tests for restore JSON API routes under /api/plugins/backup_mongo/restores/."""

from typing import Any
from unittest.mock import AsyncMock, call

import yaml
from fastapi import HTTPException, status

from app.sep.inventory import CreatedService
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.backup_mongo.restore.deps import RESTORE_CONFIG_PAYLOAD_MARKER
from app.tasks.models import TaskBackendEnum, TaskOwner
from tests.app.factories import TaskFactory

API_BASE = "/api/plugins/backup_mongo/restores"
EXPECTED_LOGICAL_RESTORE_POSTS = 3
EXPECTED_PHYSICAL_RESTORE_POSTS = 4


def build_restore_task(name: str = "mongo-restore-task", **overrides: Any) -> dict:
    """Build a fake restore_mongo task payload for route tests."""
    data_overrides = overrides.pop("data", {})
    parent = data_overrides.pop("parent", None)
    backup_type = data_overrides.pop("backup_type", BackupType.PBM_LOGICAL.value)
    is_parent = parent is None and RESTORE_CONFIG_PAYLOAD_MARKER in str(
        data_overrides.get("payload", RESTORE_CONFIG_PAYLOAD_MARKER)
    )
    if is_parent and "payload" not in data_overrides:
        payload_file = RESTORE_CONFIG_PAYLOAD_MARKER
    elif parent:
        if backup_type == BackupType.PBM_LOGICAL.value:
            payload_file = "pbm_logical_restore_payload"
        else:
            payload_file = "pbm_physical_restore_payload"
    elif "pbm-list" in name:
        payload_file = "pbm_list_payload"
    elif "pbm-force-resync" in name:
        payload_file = "pbm_force_resync_payload"
    else:
        payload_file = RESTORE_CONFIG_PAYLOAD_MARKER

    config = yaml.dump(
        {
            "backupType": backup_type,
            "backupSource": "2026-04-29T10:00:00",
        },
        default_flow_style=False,
    )
    task = TaskFactory.build(
        name=name,
        owner=TaskOwner.RESTORE_MONGO,
        backend=TaskBackendEnum.PROXY,
        **overrides,
    )
    payload = task.model_dump(mode="json")
    payload["data"] = {
        "task": "run-python",
        "meta": {
            "target": "mongo-restore-host",
            "config": config,
            "requirements": "packaging\nPyYAML",
        },
        "payload": f"file:///plugins/backup_mongo/restore/{payload_file}",
        **data_overrides,
    }
    if parent is not None:
        payload["data"]["parent"] = parent
    return payload


def build_restore_write_body(
    task_name: str = "mongo-restore-task",
    hostname: str = "mongo-restore-host",
    service_id: int | None = 1,
    backup_type: str = BackupType.PBM_LOGICAL.value,
    **kwargs: Any,
) -> dict:
    """Build a valid RestoreTaskWrite-compatible request body."""
    return {
        "task_name": task_name,
        "hostname": hostname,
        "service_id": service_id,
        "backup_type": backup_type,
        "backup_source": "2026-04-29T10:00:00",
        **kwargs,
    }


class TestRestoreMongoPluginSchemaEndpoint:
    """Tests for GET /api/plugins/backup_mongo/restores/schema."""

    def test_schema_returns_200(self, test_client):
        """Ensure the schema endpoint returns HTTP 200 with JSON content."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.status_code == status.HTTP_200_OK
        assert "application/json" in response.headers["content-type"]

    def test_schema_name_is_backup_mongo_restores(self, test_client):
        """Ensure the restores schema uses the dedicated plugin name."""
        response = test_client.get(f"{API_BASE}/schema")

        assert response.json()["name"] == "backup_mongo_restores"


class TestRestoreMongoApiList:
    """Tests for GET /api/plugins/backup_mongo/restores/."""

    def test_list_returns_parent_tasks_only(
        self, test_client, mock_task_api_dep
    ) -> None:
        """List only parent config tasks, not child siblings."""
        parent = build_restore_task("parent-restore")
        child = build_restore_task(
            "parent-restore-pbm_logical",
            data={"parent": "parent-restore", "payload": "pbm_logical_restore_payload"},
        )
        mock_task_api_dep.get = AsyncMock(
            return_value={"items": [parent, child], "total": 2}
        )

        response = test_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_200_OK
        assert len(response.json()) == 1
        assert response.json()[0]["name"] == "parent-restore"


class TestRestoreMongoApiCreate:
    """Tests for POST /api/plugins/backup_mongo/restores/."""

    def test_create_logical_posts_three_tasks(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        mongo_service: CreatedService,
    ) -> None:
        """POST creates config, restore leg, and pbm-list for logical restores."""
        mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
        mock_task_api_dep.post = AsyncMock(
            side_effect=[
                build_restore_task("mongo-restore-task"),
                build_restore_task(
                    "mongo-restore-task-pbm_logical",
                    data={"parent": "mongo-restore-task"},
                ),
                build_restore_task(
                    "mongo-restore-task-pbm-list",
                    data={"parent": "mongo-restore-task"},
                ),
            ]
        )
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                build_restore_task("mongo-restore-task"),
                {"items": []},
                build_restore_task(
                    "mongo-restore-task-pbm_logical",
                    data={"parent": "mongo-restore-task"},
                ),
                {"items": []},
                build_restore_task(
                    "mongo-restore-task-pbm-list",
                    data={"parent": "mongo-restore-task"},
                ),
                {"items": []},
            ]
        )

        response = test_client.post(
            f"{API_BASE}/",
            json=build_restore_write_body(service_id=mongo_service.id),
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.await_count == EXPECTED_LOGICAL_RESTORE_POSTS
        first_post = mock_task_api_dep.post.await_args_list[0].kwargs["json"]
        assert first_post["owner"] == TaskOwner.RESTORE_MONGO.value
        assert RESTORE_CONFIG_PAYLOAD_MARKER in first_post["data"]["payload"]

    def test_create_physical_posts_four_tasks(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        mongo_service: CreatedService,
    ) -> None:
        """POST adds force-resync for physical restores."""
        mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
        mock_task_api_dep.post = AsyncMock(
            side_effect=[
                build_restore_task(
                    "mongo-restore-task",
                    data={"backup_type": BackupType.PBM_PHYSICAL.value},
                ),
                build_restore_task(
                    "mongo-restore-task-pbm_physical",
                    data={
                        "parent": "mongo-restore-task",
                        "backup_type": BackupType.PBM_PHYSICAL.value,
                    },
                ),
                build_restore_task(
                    "mongo-restore-task-pbm-list",
                    data={"parent": "mongo-restore-task"},
                ),
                build_restore_task(
                    "mongo-restore-task-pbm-force-resync",
                    data={"parent": "mongo-restore-task"},
                ),
            ]
        )
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                build_restore_task(
                    "mongo-restore-task",
                    data={"backup_type": BackupType.PBM_PHYSICAL.value},
                ),
                {"items": []},
                build_restore_task(
                    "mongo-restore-task-pbm_physical",
                    data={
                        "parent": "mongo-restore-task",
                        "backup_type": BackupType.PBM_PHYSICAL.value,
                    },
                ),
                {"items": []},
                build_restore_task(
                    "mongo-restore-task-pbm-list",
                    data={"parent": "mongo-restore-task"},
                ),
                {"items": []},
                build_restore_task(
                    "mongo-restore-task-pbm-force-resync",
                    data={"parent": "mongo-restore-task"},
                ),
                {"items": []},
            ]
        )

        response = test_client.post(
            f"{API_BASE}/",
            json=build_restore_write_body(
                service_id=mongo_service.id,
                backup_type=BackupType.PBM_PHYSICAL.value,
            ),
        )

        assert response.status_code == status.HTTP_201_CREATED
        assert mock_task_api_dep.post.await_count == EXPECTED_PHYSICAL_RESTORE_POSTS

    def test_create_rolls_back_on_mid_chain_failure(
        self,
        test_client,
        mock_task_api_dep,
        mock_inventory_api_dep,
        mongo_service: CreatedService,
    ) -> None:
        """Rollback DELETEs created tasks when a child POST fails."""
        mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
        mock_task_api_dep.post = AsyncMock(
            side_effect=[
                build_restore_task("mongo-restore-task"),
                build_restore_task(
                    "mongo-restore-task-pbm_logical",
                    data={"parent": "mongo-restore-task"},
                ),
                HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR),
            ]
        )
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.post(
            f"{API_BASE}/",
            json=build_restore_write_body(service_id=mongo_service.id),
        )

        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert mock_task_api_dep.delete.await_args_list == [
            call("/mongo-restore-task-pbm_logical"),
            call("/mongo-restore-task"),
        ]


class TestRestoreMongoApiDetail:
    """Tests for GET /api/plugins/backup_mongo/restores/{task_name}."""

    def test_detail_includes_child_tasks(self, test_client, mock_task_api_dep) -> None:
        """Detail aggregates child task statuses."""
        parent = build_restore_task("parent-restore")
        restore_leg = build_restore_task(
            "parent-restore-pbm_logical",
            data={"parent": "parent-restore"},
        )
        pbm_list = build_restore_task(
            "parent-restore-pbm-list",
            data={"parent": "parent-restore"},
        )
        mock_task_api_dep.get = AsyncMock(
            side_effect=[
                parent,
                parent,
                {"items": []},
                restore_leg,
                {"items": []},
                pbm_list,
                {"items": []},
            ]
        )

        response = test_client.get(f"{API_BASE}/parent-restore")

        assert response.status_code == status.HTTP_200_OK
        body = response.json()
        assert body["name"] == "parent-restore"
        child_names = {item["name"] for item in body["derived_tasks"]}
        assert child_names == {
            "parent-restore-pbm_logical",
            "parent-restore-pbm-list",
        }


class TestRestoreMongoApiDelete:
    """Tests for DELETE /api/plugins/backup_mongo/restores/{task_name}."""

    def test_delete_removes_parent_and_all_children(
        self, test_client, mock_task_api_dep
    ) -> None:
        """DELETE cascades to every child before the parent."""
        parent = build_restore_task("parent-restore")
        mock_task_api_dep.get = AsyncMock(return_value=parent)
        mock_task_api_dep.delete = AsyncMock(return_value=None)

        response = test_client.delete(f"{API_BASE}/parent-restore")

        assert response.status_code == status.HTTP_204_NO_CONTENT
        assert mock_task_api_dep.delete.await_args_list == [
            call("/parent-restore-pbm_logical"),
            call("/parent-restore-pbm-list"),
            call("/parent-restore"),
        ]


class TestRestoreMongoApiAuth:
    """Tests for API authentication."""

    def test_unauthenticated_list_returns_401(self, unauthenticated_client) -> None:
        """Reject unauthenticated access to the restores API."""
        response = unauthenticated_client.get(f"{API_BASE}/")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

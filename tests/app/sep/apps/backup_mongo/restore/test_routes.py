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

"""Define tests for the app.sep.apps.backup_mongo.restore.routes module."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml
from fastapi import status

from app.sep.apps.backup_mongo.restore.deps import get_restores_index_context
from app.sep.apps.backup_mongo.restore.models import RestoreCreate
from app.sep.inventory import CreatedService
from app.sep.main import sep_app
from app.tasks.models import TaskBackendEnum
from tests.app.factories import TaskFactory

EXPECTED_LOGICAL_RESTORE_POSTS = 3


def test_pbm_restores_create_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    restore_create: RestoreCreate,
    mongo_service: CreatedService,
):
    """POST /backup_mongo/restores/ resolves the real dep graph and tags every sub-task with _service_name."""
    mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/backup_mongo/restores/",
        data=restore_create.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    # Logical restores POST 3 sub-tasks (config, restore, pbm-list); physical adds force-resync.
    assert mock_task_api_dep.post.await_count == EXPECTED_LOGICAL_RESTORE_POSTS
    for call in mock_task_api_dep.post.await_args_list:
        posted = call.kwargs["json"]
        assert posted["data"]["meta"]["_service_name"] == mongo_service.name


def test_pbm_restores_update_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    restore_create: RestoreCreate,
    mongo_service: CreatedService,
):
    """POST /backup_mongo/restores/{task_name}/update resolves the real dep graph for updates too."""
    mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
    mock_task_api_dep.put.return_value = AsyncMock()

    response = test_client.post(
        f"/backup_mongo/restores/{restore_create.task_name}/update",
        data=restore_create.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.put.assert_awaited_once()
    posted = mock_task_api_dep.put.await_args.kwargs["json"]
    assert posted["data"]["meta"]["_service_name"] == mongo_service.name


def test_pbm_restores_detail_tolerates_missing_backup_type(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
):
    """GET detail returns 200 when config has no backupType."""
    task = TaskFactory.build(
        name="mongo-restore-task",
        owner="RESTORE_MONGO",
        backend=TaskBackendEnum.PROXY,
    ).model_dump(mode="json")
    task["data"] = {
        "task": "run-python",
        "meta": {
            "target": "mongo-restore-host",
            "config": yaml.dump(
                {
                    "backupSource": "2026-04-29T10:00:00",
                    "restore": {},
                },
                default_flow_style=False,
            ),
            "requirements": "packaging\nPyYAML",
        },
        "payload": "file:///plugins/backup_mongo/restore/restore_config_payload",
    }

    async def _mock_get(path: str, **kwargs: Any):
        if path == "/mongo-restore-task":
            return task
        if path == "/":
            return {"items": [task], "total": 1}
        if path == "/hosts/":
            return {}
        if path == "/services/":
            return {"items": []}
        if path.startswith("/stats/"):
            return {}
        if path.endswith("/history/"):
            return {"items": []}
        raise AssertionError(f"Unexpected path: {path!r}, kwargs={kwargs!r}")

    mock_task_api_dep.get = AsyncMock(side_effect=_mock_get)
    mock_inventory_api_dep.get = AsyncMock(return_value={"items": []})

    response = test_client.get("/backup_mongo/restores/mongo-restore-task")

    assert response.status_code == status.HTTP_200_OK


@pytest.fixture
def _mock_get_restores_index_context_dep():
    """Mock the get_restores_index_context dependency with a stub context."""
    sep_app.dependency_overrides[get_restores_index_context] = lambda: {
        "user": "default_user",
    }
    yield
    sep_app.dependency_overrides = {}


@pytest.mark.usefixtures("_mock_get_restores_index_context_dep")
def test_pbm_restores_index(test_client):
    """GET /backup_mongo/restores/ renders the index via the relocated RestoresIndexContext alias."""
    response = test_client.get("/backup_mongo/restores/")

    assert response.status_code == status.HTTP_200_OK
    assert response.headers["content-type"] == "text/html; charset=utf-8"

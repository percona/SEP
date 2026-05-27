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

"""Define tests for the app.sep.plugins.backup_mongo.restore.routes module."""

from unittest.mock import AsyncMock

from fastapi import status

from app.sep.inventory import CreatedService
from app.sep.plugins.backup_mongo.restore.models import RestoreCreate

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

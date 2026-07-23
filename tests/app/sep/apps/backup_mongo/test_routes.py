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

"""Define tests for the app.sep.apps.backup_mongo.routes module."""

from unittest.mock import AsyncMock

from fastapi import status

from app.sep.apps.backup_mongo.models import BackupCreate
from app.sep.inventory import CreatedService

EXPECTED_PBM_TASK_POSTS = 5


def test_pbm_backups_create_full_form_dependency_chain_without_payload_override(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    backup_create: BackupCreate,
    mongo_service: CreatedService,
):
    """POST /backup_mongo/ resolves the real dep graph and tags meta with _service_name."""
    mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
    mock_task_api_dep.post.return_value = AsyncMock()

    response = test_client.post(
        "/backup_mongo/",
        data=backup_create.model_dump(exclude_none=True),
        follow_redirects=False,
    )
    assert response.status_code == status.HTTP_303_SEE_OTHER
    # The route fans out the config task to PBM logical/physical/status sub-tasks.
    assert mock_task_api_dep.post.await_count == EXPECTED_PBM_TASK_POSTS
    posted = mock_task_api_dep.post.await_args_list[0].kwargs["json"]
    assert posted["name"] == backup_create.task_name
    assert posted["owner"] == "BACKUP_MONGO"
    assert posted["data"]["meta"]["_service_name"] == mongo_service.name


def test_pbm_backups_create_rejects_malformed_priority_yaml(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    backup_create: BackupCreate,
    mongo_service: CreatedService,
):
    """Reject malformed Node Priority YAML without creating tasks.

    The legacy Jinja path surfaces validation errors as a flash message + 303 redirect
    (see the app-wide ``RequestValidationError`` handler), not a raw 422.
    """
    mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
    data = backup_create.model_dump(exclude_none=True)
    data["backup_priority"] = '"h1:27018": 2 "h2:27018": 2'

    response = test_client.post("/backup_mongo/", data=data, follow_redirects=False)

    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()


def test_pbm_backups_create_rejects_s3_storage_without_bucket(
    test_client,
    mock_task_api_dep,
    mock_inventory_api_dep,
    backup_create: BackupCreate,
    mongo_service: CreatedService,
):
    """Reject an S3 storage config missing a bucket without creating tasks.

    The legacy Jinja path surfaces validation errors as a flash message + 303
    redirect, not a raw 422.
    """
    mock_inventory_api_dep.get = AsyncMock(return_value=mongo_service.model_dump())
    data = backup_create.model_dump(exclude_none=True)
    data["storage_type"] = "s3"
    data["storage_s3_region"] = "eu-west-1"
    data.pop("storage_filesystem_path", None)

    response = test_client.post("/backup_mongo/", data=data, follow_redirects=False)

    assert response.status_code == status.HTTP_303_SEE_OTHER
    mock_task_api_dep.post.assert_not_awaited()

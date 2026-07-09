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

"""Define fixtures for the app.sep.apps.backup_mongo tests."""

import pytest

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_mongo.models import BackupCreate, BackupType
from app.sep.inventory import CreatedNode, CreatedService
from tests.app.factories import CreatedServiceFactory
from tests.app.sep.conftest import (  # noqa: F401
    mock_inventory_api_dep,
    mock_task_api_dep,
)


@pytest.fixture
def mongo_service(created_node: CreatedNode) -> CreatedService:
    """Return a fake created MongoDB service."""
    return CreatedServiceFactory.build(node=created_node, type=ServiceTypeEnum.MONGODB)


@pytest.fixture
def backup_create(mongo_service: CreatedService) -> BackupCreate:
    """Define a sample MongoDB BackupCreate form."""
    return BackupCreate(
        task_name="mongo-backup-task",
        hostname="mongo-host",
        service_id=mongo_service.id,
        backup_type=BackupType.PBM_CONFIG,
        storage_type="filesystem",
        storage_filesystem_path="/var/backups/mongo",
        pitr_compression="snappy",
    )

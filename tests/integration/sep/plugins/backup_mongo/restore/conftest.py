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

"""Define fixtures for the app.sep.plugins.backup_mongo.restore tests."""

import pytest

from app.sep.inventory import CreatedService
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.backup_mongo.restore.models import RestoreCreate


@pytest.fixture
def restore_create(mongo_service: CreatedService) -> RestoreCreate:
    """Define a sample MongoDB RestoreCreate form with a service_id set."""
    return RestoreCreate(
        hostname="mongo-restore-host",
        task_name="mongo-restore-task",
        service_id=str(mongo_service.id),
        backup_type=BackupType.PBM_LOGICAL,
        backup_source="2026-04-29T10:00:00",
    )


@pytest.fixture
def restore_create_no_service() -> RestoreCreate:
    """Define a sample MongoDB RestoreCreate form without a service_id."""
    return RestoreCreate(
        hostname="mongo-restore-host",
        task_name="mongo-restore-task",
        service_id=None,
        backup_type=BackupType.PBM_LOGICAL,
        backup_source="2026-04-29T10:00:00",
    )

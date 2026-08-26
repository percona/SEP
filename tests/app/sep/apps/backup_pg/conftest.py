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

"""Define fixtures for the app.sep.apps.backup_pg tests.

Overrides the shared :func:`mock_inventory_api` fixture so the seeded service is
PostgreSQL-typed: backup_pg's create model resolves a single-type
``ServiceRef(POSTGRESQL)``, which ``get_created_entity``'s equality filter
rejects against the kit's MySQL default.
"""

import pytest
import yaml

from app.inventory.models import ServiceTypeEnum
from app.sep.apps.backup_pg.models import BackupPgForm, BackupType
from app.tasks.models import Task
from tests.app.factories import MOCK_CREATED_SERVICE_ID, TaskFactory
from tests.app.sep.apps.framework.kit import MockInventoryAPI


@pytest.fixture
def mock_inventory_api() -> MockInventoryAPI:
    """Return an Inventory-API mock whose seeded service is PostgreSQL-typed."""
    api = MockInventoryAPI()
    api.seed_service(MOCK_CREATED_SERVICE_ID, service_type=ServiceTypeEnum.POSTGRESQL)
    return api


@pytest.fixture
def backup_create() -> BackupPgForm:
    """Define a sample backup_pg create form for the Jinja form-path tests."""
    return BackupPgForm(
        task_name="fake_task",
        hostname="localhost",
        service_id=1,
        stanza="sep-test",
        backup_dir="/var/lib/pgbackrest",
    )


@pytest.fixture
def created_task() -> Task:
    """Return a fake created backup_pg Task instance."""
    return TaskFactory.build(
        owner="BACKUP_PG",
        data={
            "meta": {
                "target": "localhost",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": 5432,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                ),
            }
        },
    )


# Spelled out on purpose: this is the cadence vocabulary the product promises, so a
# test that read it back off a model or the payload would assert a surface against
# itself. ``literal_members`` answers the separate question of whether two surfaces
# agree with each other.
PGBACKREST_INCREMENTAL_CYCLES = (
    "daily",
    "weekly",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
)

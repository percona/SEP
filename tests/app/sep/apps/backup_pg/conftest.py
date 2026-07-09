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
from app.sep.apps.backup_pg.deps import (
    build_backup_task_payload,
    get_backups_index_context,
    get_backups_task,
)
from app.sep.apps.backup_pg.models import BackupPgForm, BackupType
from app.sep.main import sep_app
from app.tasks.models import Task, TaskBackendEnum, TaskWrite
from tests.app.factories import MOCK_CREATED_SERVICE_ID, TaskFactory
from tests.app.sep.apps.framework.kit import MockInventoryAPI


@pytest.fixture
def mock_inventory_api() -> MockInventoryAPI:
    """Return an Inventory-API mock whose seeded service is PostgreSQL-typed."""
    api = MockInventoryAPI()
    api.seed_service(MOCK_CREATED_SERVICE_ID, service_type=ServiceTypeEnum.POSTGRESQL)
    return api


@pytest.fixture
def _mock_get_backups_index_context_dep() -> None:
    """Mock the get_backups_index_context dependency for the Jinja index route."""
    sep_app.dependency_overrides[get_backups_index_context] = lambda: {
        "user": "default_user",
        "executor_hosts": [],
        "services": [],
        "tasks": [],
        "history_tasks": [],
        "running_tasks": [],
        "alert_on_fail_default": False,
        "alert_on_fail_available": False,
        "connectivity_check_default": True,
    }
    yield
    sep_app.dependency_overrides = {}


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


@pytest.fixture
def _mock_get_backups_task_dep(created_task: Task) -> None:
    """Mock the get_backups_task dependency."""
    sep_app.dependency_overrides[get_backups_task] = lambda: created_task
    yield
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_build_backup_task_payload_dep() -> TaskWrite:
    """Mock the build_backup_task_payload dependency for the Jinja create route."""
    fake_task_write = TaskWrite(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner="BACKUP_PG",
        data={"task": "fake-task", "meta": {}, "payload": ""},
    )
    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write
    yield fake_task_write
    sep_app.dependency_overrides = {}

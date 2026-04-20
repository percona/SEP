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

"""Define fixtures for the app.sep.plugins.backup_pg tests."""

import pytest
import yaml

from app.sep.main import sep_app
from app.sep.plugins.backup_pg.deps import (
    build_backup_task_payload,
    get_backups_index_context,
    get_backups_task,
)
from app.sep.plugins.backup_pg.models import BackupCreate, BackupType
from app.sep.plugins.backup_pg.routes import router as backup_pg_router
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite
from tests.app.factories import TaskFactory

if not any(route.path.startswith("/backup-pg") for route in sep_app.routes):
    sep_app.include_router(backup_pg_router, prefix="/backup-pg")


@pytest.fixture
def _mock_get_backups_index_context_dep() -> None:
    """Mock the get_backups_index_context dependency."""
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
def backup_create() -> BackupCreate:
    """Define a sample BackupCreate form data."""
    return BackupCreate(
        task_name="fake_task",
        hostname="localhost",
        service_id=1,
        backup_type=BackupType.PGBACKREST,
    )


@pytest.fixture
def created_task() -> Task:
    """Return a fake created Task instance."""
    return TaskFactory.build(
        owner=TaskOwner.BACKUP_PG,
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
    """Mock the build_backup_task_payload dependency."""
    fake_task_write = TaskWrite(
        name="fake_task",
        backend=TaskBackendEnum.PROXY,
        owner=TaskOwner.BACKUP_PG,
        data={"task": "fake-task", "meta": {}, "payload": ""},
    )
    sep_app.dependency_overrides[build_backup_task_payload] = lambda: fake_task_write
    yield fake_task_write
    sep_app.dependency_overrides = {}

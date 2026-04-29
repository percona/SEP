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

"""Define tests for the app.sep.plugins.backup_mongo.restore.deps module."""

from collections.abc import Awaitable, Callable

import pytest

from app.inventory.models import ServiceTypeEnum
from app.sep.inventory import CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.plugins.backup_mongo.models import BackupType
from app.sep.plugins.backup_mongo.restore.deps import (
    _resolve_service_name,
    build_pbm_force_resync_task_payload,
    build_pbm_list_task_payload,
    build_restore_config_task_payload,
    build_restore_task_payload,
    build_restore_tasks,
)
from app.sep.plugins.backup_mongo.restore.models import RestoreCreate
from app.tasks.models import TaskWrite

EXPECTED_PHYSICAL_RESTORE_TUPLE_LEN = 4

DispatchFn = Callable[[RestoreCreate, object], Awaitable[TaskWrite]]
DISPATCH_FUNCTIONS: list[DispatchFn] = [
    build_restore_config_task_payload,
    build_restore_task_payload,
    build_pbm_list_task_payload,
    build_pbm_force_resync_task_payload,
]


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", DISPATCH_FUNCTIONS)
async def test_dispatch_includes_service_name_when_service_id_set(
    dispatch: DispatchFn,
    mocker,
    mock_remote_api,
    restore_create: RestoreCreate,
    mongo_service: CreatedService,
):
    """All four mongo restore dispatch functions inject _service_name when service_id is set."""
    mocker.patch(
        "app.sep.plugins.backup_mongo.restore.deps.get_created_entity",
        return_value=mongo_service,
    )

    task_payload = await dispatch(restore_create, mock_remote_api)

    assert task_payload.data["meta"]["_service_name"] == mongo_service.name


@pytest.mark.asyncio
@pytest.mark.parametrize("dispatch", DISPATCH_FUNCTIONS)
async def test_dispatch_omits_service_name_when_service_id_unset(
    dispatch: DispatchFn,
    mocker,
    mock_remote_api,
    restore_create_no_service: RestoreCreate,
):
    """All four dispatch functions skip the lookup and meta key when service_id is None."""
    get_created_entity = mocker.patch(
        "app.sep.plugins.backup_mongo.restore.deps.get_created_entity",
    )

    task_payload = await dispatch(restore_create_no_service, mock_remote_api)

    assert "_service_name" not in task_payload.data["meta"]
    get_created_entity.assert_not_called()


@pytest.mark.asyncio
async def test_resolve_service_name_returns_none_when_service_id_missing(
    mock_remote_api,
    restore_create_no_service: RestoreCreate,
):
    """_resolve_service_name returns None when the form has no service_id."""
    assert (
        await _resolve_service_name(restore_create_no_service, mock_remote_api) is None
    )


@pytest.mark.asyncio
async def test_resolve_service_name_returns_service_name_when_service_id_present(
    mocker,
    mock_remote_api,
    restore_create: RestoreCreate,
    mongo_service: CreatedService,
):
    """_resolve_service_name returns service.name and queries with the MONGODB type."""
    get_created_entity = mocker.patch(
        "app.sep.plugins.backup_mongo.restore.deps.get_created_entity",
        return_value=mongo_service,
    )

    result = await _resolve_service_name(restore_create, mock_remote_api)

    assert result == mongo_service.name
    get_created_entity.assert_awaited_once_with(
        mock_remote_api,
        SyncInventoryEntityTypeEnum.SERVICE,
        restore_create.service_id,
        type=ServiceTypeEnum.MONGODB,
    )


@pytest.mark.asyncio
async def test_build_restore_tasks_threads_inventory_api_to_all_dispatch_fns(
    mocker,
    mock_remote_api,
    mongo_service: CreatedService,
):
    """build_restore_tasks returns a 4-tuple with _service_name set on every sub-task for physical restores."""
    mocker.patch(
        "app.sep.plugins.backup_mongo.restore.deps.get_created_entity",
        return_value=mongo_service,
    )
    physical_form = RestoreCreate(
        hostname="mongo-restore-host",
        task_name="mongo-restore-task",
        service_id=str(mongo_service.id),
        backup_type=BackupType.PBM_PHYSICAL,
        backup_source="2026-04-29T10:00:00",
    )

    tasks = await build_restore_tasks(physical_form, mock_remote_api)

    assert len(tasks) == EXPECTED_PHYSICAL_RESTORE_TUPLE_LEN
    assert all(task is not None for task in tasks)
    for task in tasks:
        assert task.data["meta"]["_service_name"] == mongo_service.name


@pytest.mark.asyncio
async def test_build_restore_tasks_logical_omits_force_resync(
    mocker,
    mock_remote_api,
    restore_create: RestoreCreate,
    mongo_service: CreatedService,
):
    """Logical restores skip the force-resync sub-task (last tuple element is None)."""
    mocker.patch(
        "app.sep.plugins.backup_mongo.restore.deps.get_created_entity",
        return_value=mongo_service,
    )

    tasks = await build_restore_tasks(restore_create, mock_remote_api)

    assert len(tasks) == EXPECTED_PHYSICAL_RESTORE_TUPLE_LEN
    *populated_tasks, force_resync = tasks
    assert force_resync is None
    for task in populated_tasks:
        assert task.data["meta"]["_service_name"] == mongo_service.name

"""Define tests for the app.sep.plugins.archives.deps module."""

from unittest.mock import AsyncMock

import pytest
import yaml

from app.sep.inventory import CreatedTable
from app.sep.plugins.archives.deps import (
    build_archives_task_payload,
    get_archives_task,
    get_archives_task_info,
)
from app.sep.plugins.archives.models import ArchivesCreate, SwapDropEnum
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite
from tests.app.factories import (
    CreatedTableFactory,
    MOCK_CREATED_SCHEMA_ID,
    MOCK_CREATED_SERVICE_ID,
    MOCK_CREATED_TABLE_ID,
    MOCK_DESTINATION_TABLE_ID,
    TaskFactory,
)


@pytest.fixture
def dest_table() -> CreatedTable:
    """Return a fake destination Table."""
    dest_table = CreatedTableFactory.build()
    dest_table.id = MOCK_DESTINATION_TABLE_ID
    return dest_table


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    created_task = TaskFactory.build(owner=TaskOwner.ARCHIVER)
    mock_meta_config = yaml.dump(
        {
            "PURGE_LIST": [
                {
                    "SOURCE_DB": "mock_source_db",
                    "SOURCE_TABLE": "mock_source_table",
                    "SWAP_DROP": 1,
                }
            ]
        }
    )

    mock_data = {
        "meta": {
            "config": mock_meta_config,
            "target": "mock_target",
        }
    }
    created_task.data = mock_data
    created_task.owner = TaskOwner.ARCHIVER
    return created_task


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("created_archives", "dest_table_id"),
    [
        (
            ArchivesCreate(
                alias="SWAP_DROP",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.SWAP_DROP,
                dest_table_id=None,
                dest_file=None,
            ),
            None,
        ),
        (
            ArchivesCreate(
                alias="PURGE",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 10",
                dest_table_id=MOCK_DESTINATION_TABLE_ID,
            ),
            MOCK_DESTINATION_TABLE_ID,
        ),
    ],
)
async def test_build_archives_task_payload(
    created_archives,
    created_service,
    created_schema,
    created_table,
    dest_table,
    dest_table_id,
    mock_remote_api,
):
    """Test for building the archive task payload from form."""
    mock_remote_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
            dest_table.model_dump() if dest_table_id else None,
        ]
    )
    generated_task = await build_archives_task_payload(
        created_archives, mock_remote_api
    )

    assert isinstance(generated_task, TaskWrite)
    assert generated_task.name == created_archives.alias
    assert generated_task.backend == TaskBackendEnum.PROXY
    assert generated_task.owner == TaskOwner.ARCHIVER
    assert "task" in generated_task.data
    assert generated_task.data["task"] == "run-python"
    assert "meta" in generated_task.data
    assert "payload" in generated_task.data
    assert "file://" in generated_task.data["payload"]

    purge_config_yaml = generated_task.data["meta"]["config"]
    assert created_archives.alias in purge_config_yaml
    assert created_archives.hostname in purge_config_yaml
    assert created_schema.name in purge_config_yaml
    assert created_table.name in purge_config_yaml
    if dest_table_id:
        assert dest_table.name in purge_config_yaml


@pytest.mark.asyncio
async def test_get_archives_task(created_task, mock_remote_api):
    """Test for fetching and validating a task for the Archives plugin."""
    mock_remote_api.get = AsyncMock(side_effect=[created_task.model_dump()])
    alters_task = await get_archives_task(created_task.name, mock_remote_api)
    assert isinstance(alters_task, Task)


def test_get_archives_task_info(created_task):
    """Test for extracting relevant information from a task for the Archives plugin."""
    expected_output = {
        "hostname": "mock_target",
        "source": "mock_source_db.mock_source_table",
        "dest": None,
    }
    result = get_archives_task_info(created_task.model_dump())
    assert result == expected_output

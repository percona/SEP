"""Define tests for the app.sep.plugins.alters.deps module."""

from unittest.mock import AsyncMock

import pytest

from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    get_alters_task,
    get_alters_task_info,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite
from tests.app.factories import (
    AltersCreateFactory,
    TaskFactory,
)


@pytest.fixture
def created_alters(created_service, created_schema, created_table) -> AltersCreate:
    """Return a fake created AltersCreate instance."""
    created_alters = AltersCreateFactory.build()
    created_alters.service_id = created_service.id
    created_alters.schema_id = created_schema.id
    created_alters.table_id = created_table.id
    created_alters.alter = "ADD COLUMN new_column INT"
    created_alters.recursion_method = "dsn"
    return created_alters


@pytest.fixture
def created_task() -> Task:
    """Return a fake created task."""
    created_task = TaskFactory.build(
        owner=TaskOwner.ALTERS, backend=TaskBackendEnum.PROXY
    )
    created_task.data = {
        "meta": {
            "_schema_name": "db",
            "_table_name": "tbl",
            "args": "'--alter=ADD COLUMN testalter VARCHAR(50) AFTER name' h=127.0.0.1,P=3306,D=db,t=tbl --recursion-method=processlist --print --progress=time,10 --execute",
            "command": "pt-online-schema-change",
            "target": "localhost",
        },
        "task": "run-command",
    }
    return created_task


@pytest.mark.asyncio
async def test_build_alters_task_payload(
    created_alters, created_service, created_schema, created_table, mock_remote_api
):
    """Test for building the alter task payload from form."""
    mock_remote_api.get = AsyncMock(
        side_effect=[
            created_service.model_dump(),
            created_schema.model_dump(),
            created_table.model_dump(),
        ]
    )
    generated_task = await build_alters_task_payload(created_alters, mock_remote_api)
    assert isinstance(generated_task, TaskWrite)
    assert generated_task.owner == TaskOwner.ALTERS

    assert generated_task.data["task"] == "run-command"
    meta = generated_task.data["meta"]
    assert meta["command"] == "pt-online-schema-change"
    assert "--alter=ADD COLUMN new_column INT" in meta["args"]
    assert "--execute" in meta["args"]


@pytest.mark.asyncio
async def test_get_alters_task(created_task, mock_remote_api):
    """Test for fetching and validating a task for the Alters plugin."""
    mock_remote_api.get = AsyncMock(side_effect=[created_task.model_dump()])
    alters_task = await get_alters_task(created_task.name, mock_remote_api)
    assert isinstance(alters_task, Task)
    assert alters_task.name == created_task.name


def test_get_alters_task_info(created_task):
    """Test for extracting relevant information from a task for the Alters plugin."""
    result = get_alters_task_info(created_task.model_dump())
    assert result == {
        "hostname": "localhost",
        "table": "db.tbl",
    }

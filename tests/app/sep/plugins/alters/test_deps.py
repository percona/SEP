"""Define tests for the app.sep.plugins.alters.deps module."""

from unittest.mock import AsyncMock

import pytest

from app.sep.plugins.alters.deps import (
    build_alters_task_payload,
    extract_service_info,
    get_alters_task,
    get_alters_task_info,
    parse_alters_task_args,
)
from app.sep.plugins.alters.models import AltersCreate
from app.tasks.models import Task, TaskOwner, TaskWrite
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
    created_task = TaskFactory.build(owner=TaskOwner.ALTERS)
    mock_data = {
        "task": "run-command",
        "meta": {
            "command": "pt-online-schema-change",
            "args": "--alter=ADD COLUMN new_column INT --execute",
            "target": "localhost",
            "_schema_name": "public",
            "_table_name": "example_table",
        },
    }

    created_task.data = mock_data
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

    command = generated_task.data["meta"]["command"]
    assert command == "pt-online-schema-change"


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
        "table": "public.example_table",
        "parent": None,
    }


def test_extract_service_info_from_meta():
    """Test extracting service info from meta fields."""
    meta = {
        "_service_host": "db.example.com",
        "_service_port": 3307,
        "_schema_name": "test_schema",
        "_table_name": "test_table",
    }

    result = extract_service_info(meta)

    assert result == {
        "service_host": "db.example.com",
        "service_port": 3307,
        "schema_name": "test_schema",
        "table_name": "test_table",
    }


def test_extract_service_info_from_args():
    """Test extracting service info from args when meta fields are missing."""
    meta = {
        "args": "'--alter=ADD COLUMN x INT' h=db.example.com,P=3307 --execute",
    }

    result = extract_service_info(meta)

    assert result == {
        "service_host": "db.example.com",
        "service_port": 3307,
        "schema_name": "",
        "table_name": "",
    }


def test_parse_alters_task_args():
    """Test parsing alters task arguments back into form field values."""
    meta = {
        "args": "'--alter=ADD INDEX c_1(chunk)' P=3306,D=percona,t=careers --recursion-method=processlist --pause-file=/tmp/pause_file.txt --tries=create_triggers:10000:1,drop_triggers:10000:1,copy_rows:10000:1 '--set-vars=transaction_isolation='\"'\"'READ-COMMITTED'\"'\"',lock_wait_timeout=5' --critical-load=Threads_running=99999,Connections=200 --max-load=Threads_running=30,Threads_connected=120 --chunk-time=0.5 --max-lag=150 --print --progress=time,10 --execute",
    }

    result = parse_alters_task_args(meta)

    assert result == {
        "alter": "ADD INDEX c_1(chunk)",
        "recursion_method": "processlist",
        "dsn_table": "",
        "pause_file": "/tmp/pause_file.txt",
        "new_table_name": "",
        "print_arg": True,
        "progress": "time,10",
        "no_swap_tables": False,
        "no_drop_old_table": False,
        "no_drop_new_table": False,
        "no_drop_triggers": False,
        "tries": "create_triggers:10000:1,drop_triggers:10000:1,copy_rows:10000:1",
        "set_vars": "transaction_isolation='READ-COMMITTED',lock_wait_timeout=5",
        "critical_load": "Threads_running=99999,Connections=200",
        "max_load": "Threads_running=30,Threads_connected=120",
        "chunk_time": "0.5",
        "max_lag": "150",
        "max_flow_ctl": "",
    }

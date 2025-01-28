"""Define tests for the app.sep.plugins.backup.deps module."""

from unittest.mock import AsyncMock

import pytest
import yaml

from app.sep.inventory import CreatedNode, CreatedService
from app.sep.plugins.backup.deps import (
    build_backup_task_payload,
    get_backups_task,
    get_backups_task_info,
)
from app.sep.plugins.backup.models import BackupCreate, BackupType
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "backup_type",
        "expected_payload_filename",
        "expected_requirements",
        "expected_host",
    ),
    [
        (
            BackupType.MYDUMPER,
            "mydumper_payload",
            "packaging\nPyYAML\nPyMySQL\nboto3",
            "fake-address",
        ),
        (
            BackupType.XTRABACKUP,
            "xtrabackup_payload",
            "packaging\nPyYAML\nPyMySQL\nboto3\nfilelock",
            "localhost",
        ),
    ],
)
async def test_build_backup_task_payload(
    backup_type: BackupType,
    expected_payload_filename,
    expected_requirements,
    expected_host,
    faker,
    mocker,
    mock_remote_api,
    created_service: CreatedService,
):
    """Test build_backup_task_payload.

    Test that build_backup_task_payload generates the correct TaskWrite
    depending on the backup_type, encryption, and other fields.
    """
    mocker.patch(
        "app.sep.plugins.backup.deps.get_created_entity",
        return_value=created_service,
    )
    created_service.node = CreatedNode(
        id=1,
        address="fake-address",
    )

    form_data = {
        "service_id": created_service.id,
        "task_name": "test_task",
        "backup_type": backup_type,
        "hostname": "test_host",
        "s3_bucket": "my-test-bucket",
        "rsync_path": "/rsync",
        "encryption_recipient": faker.email(),
    }
    backup_create = BackupCreate(**form_data)

    task_payload: TaskWrite = await build_backup_task_payload(
        backup_create, mock_remote_api
    )

    assert isinstance(task_payload, TaskWrite)
    assert task_payload.name == form_data["task_name"]
    assert task_payload.backend == TaskBackendEnum.PROXY
    assert task_payload.owner == TaskOwner.BACKUPS

    data = task_payload.data
    assert data["task"] == "run-python"

    meta = data["meta"]
    assert meta["target"] == form_data["hostname"]
    assert meta["requirements"] == expected_requirements

    cfg = yaml.safe_load(meta["config"])
    server_list = cfg["SERVER_LIST"]
    assert len(server_list) == 1
    server_config = server_list[0]

    assert server_config["HOST"] == expected_host
    if backup_type == BackupType.MYDUMPER:
        assert server_config["BACKUP_TYPE"] == BackupType.MYDUMPER.value
    else:
        assert server_config["BACKUP_TYPE"] == BackupType.XTRABACKUP.value

    assert "s3" in server_config["UPLOAD"]
    assert "rsync" in server_config["UPLOAD"]

    assert data["payload"].startswith("file://")
    assert expected_payload_filename in data["payload"]


@pytest.mark.asyncio
async def test_build_backup_task_payload_raises_for_invalid_backup_type(
    faker, mocker, created_service, mock_remote_api
):
    """Test that passing an invalid BackupType raises ValueError."""
    mocker.patch(
        "app.sep.plugins.backup.deps.get_created_entity",
        return_value=created_service,
    )

    backup_create = BackupCreate.model_construct(
        service_id=created_service.id,
        task_name="test_task",
        hostname="test_host",
        backup_type="invalid",
    )

    with pytest.raises(ValueError, match="Invalid Backup Type"):
        await build_backup_task_payload(backup_create, mock_remote_api)


@pytest.mark.asyncio
async def test_get_backups_task(mocker):
    """Test get_backups_task calls get_task_by_name and returns the correct Task."""
    fake_task = Task(
        name="test_task",
        owner=TaskOwner.BACKUPS,
        data={"task": "fake-task"},
    )
    get_task_by_name = mocker.patch(
        "app.sep.plugins.backup.deps.get_task_by_name",
        return_value=fake_task,
    )

    tasks_api = AsyncMock()
    result = await get_backups_task("test_task_name", tasks_api)

    get_task_by_name.assert_called_once_with(
        tasks_api, "test_task_name", TaskOwner.BACKUPS
    )

    assert result == fake_task


def test_get_backups_task_info():
    """Test extracting the correct fields from a task dictionary."""
    server_port = 5555
    fake_task_dict = {
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "my-db-host",
                                "PORT": server_port,
                                "UPLOAD": ["S3", "RSYNC"],
                                "BACKUP_TYPE": "X",
                            }
                        ]
                    }
                ),
            }
        }
    }

    result = get_backups_task_info(fake_task_dict)
    assert result["hostname"] == "host.example.com"
    assert result["host"] == "my-db-host"
    assert result["port"] == server_port
    assert result["upload"] == "S3, RSYNC"
    assert result["backup_type"] == BackupType.XTRABACKUP.name

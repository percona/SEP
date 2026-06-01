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

"""Define tests for the app.sep.plugins.mysql_backups.deps module."""

from unittest.mock import AsyncMock

import pytest
import yaml

from app.sep.inventory import CreatedNode, CreatedService
from app.sep.plugins.mysql_backups.deps import (
    build_backup_task_payload,
    get_backups_task,
    get_backups_task_info,
    parse_backup_task_data,
)
from app.sep.plugins.mysql_backups.models import BackupCreate, BackupType
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
            "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3\nfilelock",
            "fake-address",
        ),
        (
            BackupType.XTRABACKUP,
            "xtrabackup_payload",
            "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3\nfilelock",
            "localhost",
        ),
        (
            BackupType.BINLOG,
            "binlog_payload",
            "packaging\nPyYAML\nPyMySQL[rsa,ed25519]\nboto3",
            "10.0.0.5",
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
        "app.sep.plugins.mysql_backups.deps.get_created_entity",
        return_value=created_service,
    )
    created_service.node = CreatedNode(
        id=1,
        address="fake-address",
        node_name="fake-node",
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
    if backup_type == BackupType.BINLOG:
        form_data["binlog_alternative_host"] = "10.0.0.5"
    backup_create = BackupCreate(**form_data)

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)

    assert isinstance(task_payload, TaskWrite)
    assert task_payload.name == form_data["task_name"]
    assert task_payload.backend == TaskBackendEnum.PROXY
    assert task_payload.owner == TaskOwner.BACKUPS

    data = task_payload.data
    assert data["task"] == "run-python"

    meta = data["meta"]
    assert meta["target"] == form_data["hostname"]
    assert meta["requirements"] == expected_requirements
    assert meta["_service_name"] == created_service.name

    cfg = yaml.safe_load(meta["config"])
    server_list = cfg["SERVER_LIST"]
    assert len(server_list) == 1
    server_config = server_list[0]

    assert server_config["HOST"] == expected_host
    assert server_config["BACKUP_TYPE"] == backup_type.value

    if backup_type == BackupType.BINLOG:
        assert cfg["ALL_SERVERS"]["BINLOG_ALTERNATIVE_HOST"] == "10.0.0.5"
    else:
        assert "BINLOG_ALTERNATIVE_HOST" not in cfg["ALL_SERVERS"]

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
        "app.sep.plugins.mysql_backups.deps.get_created_entity",
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
        "app.sep.plugins.mysql_backups.deps.get_task_by_name",
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


@pytest.mark.parametrize(
    ("all_servers", "expected_alt_host"),
    [
        (
            {
                "BINLOG_ALTERNATIVE_HOST": "10.0.0.5",
                "BINLOG_PREFIX": "binlog",
            },
            "10.0.0.5",
        ),
        (
            {"BINLOG_PREFIX": "binlog"},
            None,
        ),
    ],
)
def test_parse_backup_task_data(all_servers: dict, expected_alt_host: str | None):
    """Round-trip the binlog alt host from persisted YAML on the edit form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.BINLOG.value,
                                "UPLOAD": ["gsutil"],
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["backup_type"] == BackupType.BINLOG.value
    assert result["service_id"] is None
    assert result["host"] == "10.0.0.5"
    assert result["binlog_alternative_host"] == expected_alt_host


@pytest.mark.parametrize(
    ("upload_providers", "all_servers", "expected_result"),
    [
        (
            ["s3"],
            {
                "S3_BUCKET": "my-bucket",
                "S3_STORAGE_CLASS": "STANDARD_IA",
                "SKIP_S3_SAFETY_CHECK": True,
            },
            {
                "s3_bucket": "my-bucket",
                "s3_storage_class": "STANDARD_IA",
                "skip_s3_safety_check": True,
            },
        ),
        (
            ["s3"],
            {},
            {
                "s3_bucket": None,
                "s3_storage_class": None,
                "skip_s3_safety_check": False,
            },
        ),
        (
            ["gsutil"],
            {"GS_BUCKET": "my-gs-bucket"},
            {"gs_bucket": "my-gs-bucket"},
        ),
        (
            ["gsutil"],
            {},
            {"gs_bucket": None},
        ),
        (
            ["rsync"],
            {"RSYNC_PATH": "/mnt/backups"},
            {"rsync_path": "/mnt/backups"},
        ),
        (
            ["rsync"],
            {},
            {"rsync_path": None},
        ),
        (
            ["S3"],
            {"S3_BUCKET": "case-insensitive"},
            {"s3_bucket": "case-insensitive"},
        ),
    ],
)
def test_parse_backup_task_data_storage_targets(
    upload_providers: list[str],
    all_servers: dict,
    expected_result: dict,
):
    """Round-trip S3/GSUTIL/RSYNC storage-target keys from persisted YAML on the edit form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.XTRABACKUP.value,
                                "UPLOAD": upload_providers,
                            }
                        ],
                        "ALL_SERVERS": all_servers,
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    for key, value in expected_result.items():
        assert result[key] == value


def test_parse_backup_task_data_without_all_servers():
    """parse_backup_task_data handles a YAML config with no ALL_SERVERS block."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "ALIAS": "db1-mysql",
                                "HOST": "10.0.0.5",
                                "PORT": 3306,
                                "BACKUP_TYPE": BackupType.BINLOG.value,
                                "UPLOAD": ["gsutil"],
                            }
                        ],
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["host"] == "10.0.0.5"
    assert result["binlog_alternative_host"] is None

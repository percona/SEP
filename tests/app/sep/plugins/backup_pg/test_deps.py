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

"""Define tests for the app.sep.plugins.backup_pg.deps module."""

from unittest.mock import AsyncMock

import pytest
import yaml

from app.core.exceptions import HTTPNotFoundException
from app.sep.connectivity import CONNECTIVITY_META_PORT_KEY
from app.sep.inventory import CreatedNode, CreatedService
from app.sep.plugins.backup_pg.deps import (
    build_backup_task_payload,
    get_backups_task,
    get_backups_task_info,
    parse_backup_task_data,
)
from app.sep.plugins.backup_pg.models import BackupCreate, BackupType
from app.tasks.models import Task, TaskBackendEnum, TaskOwner, TaskWrite


@pytest.mark.asyncio
async def test_build_backup_task_payload(
    faker,
    mocker,
    mock_remote_api,
    created_service: CreatedService,
):
    """Test build_backup_task_payload for backup_pg tasks."""
    mocker.patch(
        "app.sep.plugins.backup_pg.deps.get_created_entity",
        return_value=created_service,
    )
    created_service.node = CreatedNode(
        id=1,
        address="fake-address",
        node_name="fake-node",
    )

    backup_create = BackupCreate(
        service_id=created_service.id,
        task_name="test_task",
        hostname="test_host",
        backup_type=BackupType.PGBACKREST,
        stanza="sep-test",
    )

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)

    assert isinstance(task_payload, TaskWrite)
    assert task_payload.name == backup_create.task_name
    assert task_payload.backend == TaskBackendEnum.PROXY
    assert task_payload.owner == TaskOwner.BACKUP_PG

    data = task_payload.data
    assert data["task"] == "run-python"

    meta = data["meta"]
    assert meta["target"] == backup_create.hostname
    assert meta["requirements"] == "packaging\nPyYAML"
    assert meta["_service_name"] == created_service.name

    cfg = yaml.safe_load(meta["config"])
    server_list = cfg["SERVER_LIST"]
    assert len(server_list) == 1
    server_config = server_list[0]

    assert server_config["ALIAS"] == "sep-test"
    assert server_config["HOST"] == "localhost"
    assert server_config["BACKUP_TYPE"] == BackupType.PGBACKREST.value
    assert "PORT" not in server_config

    assert data["payload"].startswith("file://")
    assert "backup_pg/payload" in data["payload"]


@pytest.mark.asyncio
async def test_build_backup_task_payload_uses_stanza_as_alias(
    mocker,
    mock_remote_api,
    created_service: CreatedService,
):
    """Stanza value, not the node address, becomes the pgBackRest ALIAS."""
    mocker.patch(
        "app.sep.plugins.backup_pg.deps.get_created_entity",
        return_value=created_service,
    )
    created_service.node = CreatedNode(
        id=1,
        address="10.30.50.162",
        node_name="fake-node",
    )

    backup_create = BackupCreate(
        service_id=created_service.id,
        task_name="test_task",
        hostname="test_host",
        backup_type=BackupType.PGBACKREST,
        stanza="my-custom-stanza",
    )

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)

    cfg = yaml.safe_load(task_payload.data["meta"]["config"])
    server_config = cfg["SERVER_LIST"][0]
    assert server_config["ALIAS"] == "my-custom-stanza"
    assert server_config["ALIAS"] != created_service.node.address


@pytest.mark.asyncio
async def test_build_backup_task_payload_preserves_raw_backup_type(
    mocker, created_service, mock_remote_api
):
    """Test build_backup_task_payload preserves a raw backup_type string."""
    mocker.patch(
        "app.sep.plugins.backup_pg.deps.get_created_entity",
        return_value=created_service,
    )

    backup_create = BackupCreate.model_construct(
        service_id=created_service.id,
        task_name="test_task",
        hostname="test_host",
        backup_type="INVALID_BACKUP_TYPE",
        stanza="sep-test",
    )

    task_payload = await build_backup_task_payload(backup_create, mock_remote_api)
    cfg = yaml.safe_load(task_payload.data["meta"]["config"])
    server_config = cfg["SERVER_LIST"][0]

    assert server_config["BACKUP_TYPE"] == "INVALID_BACKUP_TYPE"


@pytest.mark.asyncio
async def test_get_backups_task(mocker):
    """Test get_backups_task calls get_task_by_name and returns the correct Task."""
    fake_task = Task(
        name="test_task",
        owner=TaskOwner.BACKUP_PG,
        data={"task": "fake-task"},
    )
    get_task_by_name = mocker.patch(
        "app.sep.plugins.backup_pg.deps.get_task_by_name",
        return_value=fake_task,
    )

    tasks_api = AsyncMock()
    result = await get_backups_task("test_task_name", tasks_api)

    get_task_by_name.assert_called_once_with(
        tasks_api, "test_task_name", TaskOwner.BACKUP_PG
    )
    assert result == fake_task


@pytest.mark.asyncio
async def test_get_backups_task_raises_http_exception(mocker):
    """Test get_backups_task propagates task-not-found errors."""
    mocker.patch(
        "app.sep.plugins.backup_pg.deps.get_task_by_name",
        side_effect=HTTPNotFoundException(),
    )

    with pytest.raises(HTTPNotFoundException):
        await get_backups_task("missing-task", AsyncMock())


def test_get_backups_task_info():
    """Test extracting the correct fields from a backup_pg task dictionary."""
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
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
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
    assert result["backup_type"] == BackupType.PGBACKREST.name


def test_get_backups_task_info_port_falls_back_to_meta():
    """Test PORT missing from YAML falls back to the meta connectivity port."""
    meta_port = 6543
    fake_task_dict = {
        "data": {
            "meta": {
                "target": "host.example.com",
                CONNECTIVITY_META_PORT_KEY: meta_port,
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "my-db-host",
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                ),
            }
        }
    }

    result = get_backups_task_info(fake_task_dict)

    assert result["port"] == meta_port


def test_parse_backup_task_data():
    """Test parsing backup task data for the backup_pg detail view."""
    expected_port = 5432
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": expected_port,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ],
                        "ALL_SERVERS": {
                            "LOGGING_DIR": "/var/log/pgbackrest",
                        },
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["backup_type"] == BackupType.PGBACKREST.value
    assert result["service_id"] is None
    assert result["host"] == "localhost"
    assert result["port"] == expected_port
    assert result["logging_dir"] == "/var/log/pgbackrest"


def test_parse_backup_task_data_port_falls_back_to_meta():
    """Test PORT missing from YAML falls back to the meta connectivity port."""
    meta_port = 6543
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                CONNECTIVITY_META_PORT_KEY: meta_port,
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ],
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["port"] == meta_port


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
    """Round-trip S3/GSUTIL/RSYNC fields from persisted YAML on the edit-form path."""
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": 5432,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
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
    """Test parse_backup_task_data handles missing ALL_SERVERS section."""
    expected_port = 5432
    fake_task_dict = {
        "name": "test_task",
        "data": {
            "meta": {
                "target": "host.example.com",
                "config": yaml.dump(
                    {
                        "SERVER_LIST": [
                            {
                                "HOST": "localhost",
                                "PORT": expected_port,
                                "BACKUP_TYPE": BackupType.PGBACKREST.value,
                            }
                        ]
                    }
                ),
            }
        },
    }

    result = parse_backup_task_data(fake_task_dict)

    assert result["name"] == "test_task"
    assert result["hostname"] == "host.example.com"
    assert result["backup_type"] == BackupType.PGBACKREST.value
    assert result["service_id"] is None
    assert result["host"] == "localhost"
    assert result["port"] == expected_port
    assert "logging_dir" not in result

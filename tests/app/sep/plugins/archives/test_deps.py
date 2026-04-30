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

"""Define tests for the app.sep.plugins.archives.deps module."""

from datetime import date
from unittest.mock import AsyncMock

import pytest
import yaml

from app.sep.inventory import CreatedTable
from app.sep.plugins.archives.deps import (
    build_archives_task_payload,
    get_archives_task,
    get_archives_task_info,
)
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    PurgeConfigItem,
    SwapDropEnum,
)
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
        (
            ArchivesCreate(
                alias="PURGE_WITH_DISABLE_BULK_INSERT",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 10",
                dest_table_id=MOCK_DESTINATION_TABLE_ID,
                disable_bulk_insert=1,
            ),
            MOCK_DESTINATION_TABLE_ID,
        ),
        (
            ArchivesCreate(
                alias="PURGE_WITHOUT_DISABLE_BULK_INSERT",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 10",
                dest_table_id=MOCK_DESTINATION_TABLE_ID,
                disable_bulk_insert=None,
            ),
            MOCK_DESTINATION_TABLE_ID,
        ),
        (
            ArchivesCreate(
                alias="SWAP_ARCHIVE_DROP_WITH_DATE_SUFFIX",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.SWAP_ARCHIVE_DROP,
                where="id > 100",
                swp_table_suffix=date(2026, 4, 29),
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
    if created_archives.disable_bulk_insert == 1:
        assert "DISABLE_BULK_INSERT: 1" in purge_config_yaml
    else:
        assert "DISABLE_BULK_INSERT:" not in purge_config_yaml

    if created_archives.swap_drop == SwapDropEnum.SWAP_ARCHIVE_DROP:
        loaded = yaml.safe_load(purge_config_yaml)
        suffix = loaded["PURGE_LIST"][0]["SWP_TABLE_SUFFIX"]
        assert isinstance(suffix, str)
        assert suffix == "2026-04-29"


def test_purge_config_item_backward_compat_without_disable_bulk_insert():
    """PurgeConfigItem must validate old YAML configs that lack DISABLE_BULK_INSERT."""
    item = PurgeConfigItem.model_validate(
        {"ALIAS": "old_task", "SWAP_DROP": 0, "WHERE": "id > 1"}
    )
    assert item.disable_bulk_insert is None


@pytest.mark.asyncio
async def test_get_archives_task(created_task, mock_remote_api):
    """Test for fetching and validating a task for the Archives plugin."""
    mock_remote_api.get = AsyncMock(side_effect=[created_task.model_dump()])
    alters_task = await get_archives_task(created_task.name, mock_remote_api)
    assert isinstance(alters_task, Task)


class TestGetArchivesTaskInfo:
    """Test get_archives_task_info across all conditional output branches."""

    @staticmethod
    def _make_task(purge_item: dict, hostname: str = "mock_target") -> dict:
        """Build a minimal task dict."""
        return {
            "data": {
                "meta": {
                    "config": yaml.dump({"PURGE_LIST": [purge_item]}),
                    "target": hostname,
                }
            },
            "created_by": None,
            "last_updated_by": None,
        }

    def test_source_table_and_hostname(self, created_task):
        """Source table and hostname are extracted from a standard task."""
        expected_output = {
            "hostname": "mock_target",
            "source_table": "mock_source_db.mock_source_table",
            "created_by": created_task.created_by,
            "last_updated_by": created_task.last_updated_by,
        }
        result = get_archives_task_info(created_task.model_dump())
        assert result == expected_output

    def test_dest_table_included_when_set(self):
        """dest_table key is included when DEST_TABLE is set alongside SOURCE_DB."""
        task = self._make_task(
            {
                "SOURCE_DB": "mydb",
                "SOURCE_TABLE": "src_tbl",
                "DEST_TABLE": "archive_tbl",
            }
        )
        result = get_archives_task_info(task)
        assert result["source_table"] == "mydb.src_tbl"
        assert result["dest_table"] == "mydb.archive_tbl"

    def test_source_query_included_when_set(self):
        """source_query key is included when SOURCE_QUERY is set."""
        task = self._make_task(
            {"SOURCE_QUERY": "SELECT `db`, `tbl` FROM information_schema.tables"}
        )
        result = get_archives_task_info(task)
        assert (
            result["source_query"]
            == "SELECT `db`, `tbl` FROM information_schema.tables"
        )
        assert "source_table" not in result

    def test_dest_file_included_when_set(self):
        """dest_file key is included when DEST_FILE is set."""
        task = self._make_task(
            {
                "SOURCE_DB": "mydb",
                "SOURCE_TABLE": "src_tbl",
                "DEST_FILE": "/tmp/archive.csv",
            }
        )
        result = get_archives_task_info(task)
        assert result["dest_file"] == "/tmp/archive.csv"
        assert result["source_table"] == "mydb.src_tbl"

    def test_source_table_absent_when_no_source_db_or_table(self):
        """source_table key is absent when SOURCE_DB and SOURCE_TABLE are not set."""
        task = self._make_task({"ALIAS": "purge_task", "SWAP_DROP": 1})
        result = get_archives_task_info(task)
        assert "source_table" not in result
        assert result["hostname"] == "mock_target"

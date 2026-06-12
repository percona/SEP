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

from unittest.mock import AsyncMock

import pytest
import yaml

from app.core.exceptions import HTTPNotFoundException, HTTPUnprocessableEntityException
from app.inventory.constants import DEFAULT_MYSQL_PORT
from app.inventory.models import ServiceTypeEnum
from app.sep.inventory import CreatedTable
from app.sep.plugins.archives.constants import SwapDropEnum
from app.sep.plugins.archives.deps import (
    _build_archives_payload,
    _resolve_destination_host_and_db,
    _resolve_destination_tables,
    _resolve_source_tables,
    build_archives_api_task_payload,
    build_archives_task_payload,
    get_archives_api_task_responses,
    get_archives_task,
    get_archives_task_info,
)
from app.sep.plugins.archives.models import (
    ArchivesCreate,
    PurgeConfigItem,
)
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)
from tests.app.factories import (
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_SCHEMA_ID,
    MOCK_CREATED_SERVICE_ID,
    MOCK_CREATED_TABLE_ID,
    MOCK_DESTINATION_TABLE_ID,
    TaskFactory,
)

EXPECTED_API_CALLS_FOR_BOTH_IDS = 2


@pytest.fixture
def dest_table() -> CreatedTable:
    """Return a fake destination Table."""
    dest_table = CreatedTableFactory.build()
    dest_table.id = MOCK_DESTINATION_TABLE_ID
    # Pin a distinct name so the self-archive guard never fires on a random
    # collision with the source table's factory-generated name.
    dest_table.name = "dest_table_distinct"
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
    ("created_archives", "dest_table_id", "expect_dest_host"),
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
            False,
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
            False,
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
            False,
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
            False,
        ),
        (
            ArchivesCreate(
                alias="PURGE_WITH_DEST_SERVICE",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 10",
                dest_table_id=MOCK_DESTINATION_TABLE_ID,
                dest_service_id=MOCK_CREATED_SERVICE_ID,
                dest_db_id=MOCK_CREATED_SCHEMA_ID,
            ),
            MOCK_DESTINATION_TABLE_ID,
            True,
        ),
        (
            ArchivesCreate(
                alias="PURGE_WITH_MANUAL_DEST",
                hostname="localhost",
                service_id=MOCK_CREATED_SERVICE_ID,
                source_db_id=MOCK_CREATED_SCHEMA_ID,
                source_table_id=MOCK_CREATED_TABLE_ID,
                swap_drop=SwapDropEnum.PURGE_ONLY,
                where="id > 10",
                dest_table_id=MOCK_DESTINATION_TABLE_ID,
                dest_host="archive.host",
                dest_port=3307,
                dest_db_name="archive_db",
            ),
            MOCK_DESTINATION_TABLE_ID,
            True,
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
    expect_dest_host,
    mock_remote_api,
):
    """Test for building the archive task payload from form."""
    api_responses = [
        created_service.model_dump(),
        created_schema.model_dump(),
        created_table.model_dump(),
    ]
    if dest_table_id:
        api_responses.append(dest_table.model_dump())

    if created_archives.dest_service_id is not None:
        api_responses.append(created_service.model_dump())
        api_responses.append(created_schema.model_dump())

    mock_remote_api.get = AsyncMock(side_effect=api_responses)
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

    assert generated_task.data["meta"]["_service_name"] == created_service.name
    assert generated_task.data["meta"]["_pmm_node_name"] == created_service.node.name

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

    if expect_dest_host:
        if created_archives.dest_service_id is not None:
            assert "DEST_HOST:" in purge_config_yaml
            assert "DEST_DB:" in purge_config_yaml
        elif created_archives.dest_host:
            assert f"DEST_HOST: {created_archives.dest_host}" in purge_config_yaml
            assert f"DEST_PORT: {created_archives.dest_port}" in purge_config_yaml
            assert f"DEST_DB: {created_archives.dest_db_name}" in purge_config_yaml
    else:
        assert "DEST_HOST:" not in purge_config_yaml
        assert "DEST_PORT:" not in purge_config_yaml
        assert "DEST_DB:" not in purge_config_yaml
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


class TestBuildArchivesApiTaskPayload:
    """Test build_archives_api_task_payload (JSON Body() path)."""

    @pytest.mark.asyncio
    async def test_delegates_to_shared_payload_builder(
        self,
        created_service,
        created_schema,
        created_table,
        dest_table,
        mock_remote_api,
    ):
        """JSON-body variant produces a valid TaskWrite via the shared builder."""
        form = ArchivesCreate(
            alias="PURGE",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 10",
            dest_table_id=MOCK_DESTINATION_TABLE_ID,
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
                dest_table.model_dump(),
            ]
        )
        result = await build_archives_api_task_payload(
            form=form, inventory_api=mock_remote_api
        )
        assert isinstance(result, TaskWrite)
        assert result.backend == TaskBackendEnum.PROXY
        assert result.owner == TaskOwner.ARCHIVER
        assert result.data["meta"]["_pmm_node_name"] == created_service.node.name


@pytest.mark.asyncio
async def test_get_archives_api_task_responses_fetches_task_statuses(mock_remote_api):
    """List responses include per-task statuses from the batch endpoint."""
    task_one = TaskFactory.build(name="archive-1", owner=TaskOwner.ARCHIVER)
    task_two = TaskFactory.build(name="archive-2", owner=TaskOwner.ARCHIVER)
    mock_remote_api.get = AsyncMock(
        return_value={"items": [task_one.model_dump(), task_two.model_dump()]}
    )
    mock_remote_api.post = AsyncMock(
        return_value={"archive-1": "success", "archive-2": "failed"}
    )

    responses = await get_archives_api_task_responses(mock_remote_api)

    assert [response.name for response in responses] == ["archive-1", "archive-2"]
    assert [response.status for response in responses] == [
        TaskHistoryStatusEnum.SUCCESS,
        TaskHistoryStatusEnum.FAILED,
    ]
    mock_remote_api.get.assert_awaited_once_with(
        "/", params={"owner": TaskOwner.ARCHIVER.value}
    )
    mock_remote_api.post.assert_awaited_once_with(
        "/history/latest", json={"names": ["archive-1", "archive-2"]}
    )


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


def _make_form_with_source_ids(**overrides) -> ArchivesCreate:
    """Create form using source_db_id and source_table_id."""
    defaults = {
        "alias": "test",
        "hostname": "host",
        "service_id": MOCK_CREATED_SERVICE_ID,
        "source_db_id": MOCK_CREATED_SCHEMA_ID,
        "source_table_id": MOCK_CREATED_TABLE_ID,
        "source_db_name": "",
        "source_table_name": "",
        "swap_drop": SwapDropEnum.PURGE_ONLY,
        "where": "id > 1",
        "dest_table_id": MOCK_DESTINATION_TABLE_ID,
        "dest_table_name": "",
        "dest_file": None,
        "dest_db_name": "",
    }
    return ArchivesCreate(**{**defaults, **overrides})


def _make_form_with_source_names(**overrides) -> ArchivesCreate:
    """Create form using source_db_name and source_table_name."""
    defaults = {
        "alias": "test",
        "hostname": "host",
        "service_id": MOCK_CREATED_SERVICE_ID,
        "source_db_id": None,
        "source_table_id": None,
        "source_db_name": "default_db",
        "source_table_name": "default_table",
        "swap_drop": SwapDropEnum.PURGE_ONLY,
        "where": "id > 1",
        "dest_table_id": MOCK_DESTINATION_TABLE_ID,
        "dest_table_name": "",
        "dest_file": None,
        "dest_db_name": "",
    }
    return ArchivesCreate(**{**defaults, **overrides})


def _make_form_with_source_query(**overrides) -> ArchivesCreate:
    """Create form using source_query (no source ID or name fields)."""
    defaults = {
        "alias": "test",
        "hostname": "host",
        "service_id": MOCK_CREATED_SERVICE_ID,
        "source_db_id": None,
        "source_table_id": None,
        "source_db_name": "",
        "source_table_name": "",
        "source_query": "SELECT id FROM foo WHERE id > 1",
        "swap_drop": SwapDropEnum.PURGE_ONLY,
        "where": "id > 1",
        "dest_table_id": MOCK_DESTINATION_TABLE_ID,
        "dest_table_name": "",
        "dest_file": None,
        "dest_db_name": "",
    }
    return ArchivesCreate(**{**defaults, **overrides})


class TestResolveSourceTables:
    """Test _resolve_source_tables across all branches and edge cases."""

    @pytest.mark.asyncio
    async def test_both_ids_resolves_schema_and_table(
        self, created_schema, created_table, mock_remote_api
    ):
        """Both source_db_id and source_table_id set: fetch schema and table."""
        mock_remote_api.get = AsyncMock(
            side_effect=[created_schema.model_dump(), created_table.model_dump()]
        )
        form = _make_form_with_source_ids()

        source_data, schema = await _resolve_source_tables(
            form, mock_remote_api, MOCK_CREATED_SERVICE_ID
        )

        assert source_data == {
            "source_db": created_schema.name,
            "source_table": created_table.name,
        }
        assert schema == created_schema
        assert mock_remote_api.get.call_count == EXPECTED_API_CALLS_FOR_BOTH_IDS

    @pytest.mark.asyncio
    async def test_manual_names_both_set(self, mock_remote_api):
        """Manual source_db_name and source_table_name: early return, no API calls."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_names(
            source_db_name="mydb", source_table_name="mytable"
        )

        source_data, schema = await _resolve_source_tables(
            form, mock_remote_api, MOCK_CREATED_SERVICE_ID
        )

        assert source_data == {"source_db": "mydb", "source_table": "mytable"}
        assert schema is None
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_schema_id_not_found_propagates_exception(self, mock_remote_api):
        """Schema fetch raises HTTPNotFoundException: propagates unchanged."""
        mock_remote_api.get = AsyncMock(side_effect=HTTPNotFoundException())
        form = _make_form_with_source_ids()

        with pytest.raises(HTTPNotFoundException):
            await _resolve_source_tables(form, mock_remote_api, MOCK_CREATED_SERVICE_ID)

    @pytest.mark.asyncio
    async def test_table_id_not_found_propagates_exception(
        self, created_schema, mock_remote_api
    ):
        """Table fetch raises HTTPNotFoundException after schema succeeds."""
        mock_remote_api.get = AsyncMock(
            side_effect=[created_schema.model_dump(), HTTPNotFoundException()]
        )
        form = _make_form_with_source_ids()

        with pytest.raises(HTTPNotFoundException):
            await _resolve_source_tables(form, mock_remote_api, MOCK_CREATED_SERVICE_ID)

    @pytest.mark.asyncio
    async def test_source_query_path_returns_empty(self, mock_remote_api):
        """source_query form: both source branches skipped, returns ({}, None) with no API calls."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_query()

        source_data, schema = await _resolve_source_tables(
            form, mock_remote_api, MOCK_CREATED_SERVICE_ID
        )

        assert source_data == {}
        assert schema is None
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_schema_service_id_mismatch_raises_error(
        self, created_schema, mock_remote_api
    ):
        """Schema returned with wrong service_id raises ValueError (post-fetch assertion)."""
        created_schema.service_id = 999  # does not match MOCK_CREATED_SERVICE_ID
        mock_remote_api.get = AsyncMock(side_effect=[created_schema.model_dump()])
        form = _make_form_with_source_ids()

        with pytest.raises(ValueError, match="service_id"):
            await _resolve_source_tables(form, mock_remote_api, MOCK_CREATED_SERVICE_ID)


class TestResolveDestinationTables:
    """Test _resolve_destination_tables across all branches and edge cases."""

    @pytest.mark.asyncio
    async def test_dest_table_id_resolves_table(self, dest_table, mock_remote_api):
        """dest_table_id set: fetch and return table name."""
        mock_remote_api.get = AsyncMock(side_effect=[dest_table.model_dump()])
        form = _make_form_with_source_ids(dest_table_id=MOCK_DESTINATION_TABLE_ID)

        result = await _resolve_destination_tables(form, mock_remote_api)

        assert result == {"dest_table": dest_table.name}
        assert mock_remote_api.get.call_count == 1

    @pytest.mark.asyncio
    async def test_manual_dest_table_name(self, mock_remote_api):
        """dest_table_id=None, manual dest_table_name: no API calls."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_table_id=None, dest_table_name="archive_tbl"
        )

        result = await _resolve_destination_tables(form, mock_remote_api)

        assert result == {"dest_table": "archive_tbl"}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_dest_file_when_no_table(self, mock_remote_api):
        """No table ID/name, dest_file set: return file path."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_table_id=None, dest_table_name="", dest_file="/tmp/out.csv"
        )

        result = await _resolve_destination_tables(form, mock_remote_api)

        assert result == {"dest_file": "/tmp/out.csv"}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_table_name_falls_through_to_dest_file(self, mock_remote_api):
        """Empty dest_table_name (not set) falls through to dest_file.

        Note: the DSL CardinalityRule treats whitespace-only strings as
        "present" (unlike the old rstrip()-based validators), so this test
        uses an empty string instead. Whitespace-only dest_table_name with
        dest_file now raises ValidationError at form-construction time.
        """
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_table_id=None,
            dest_table_name="",
            dest_file="/tmp/archive.csv",
        )

        result = await _resolve_destination_tables(form, mock_remote_api)

        assert result == {"dest_file": "/tmp/archive.csv"}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_absent_returns_empty(self, mock_remote_api):
        """All dest table fields absent (swap_drop=SWAP_DROP path): empty dict."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_table_id=None,
            dest_table_name="",
            dest_file=None,
            swap_drop=SwapDropEnum.SWAP_DROP,
            where=None,
            swp_table_suffix=None,
        )

        result = await _resolve_destination_tables(form, mock_remote_api)

        assert result == {}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_dest_table_id_not_found_propagates_exception(self, mock_remote_api):
        """dest_table_id fetch raises HTTPNotFoundException: propagates."""
        mock_remote_api.get = AsyncMock(side_effect=HTTPNotFoundException())
        form = _make_form_with_source_ids(dest_table_id=MOCK_DESTINATION_TABLE_ID)

        with pytest.raises(HTTPNotFoundException):
            await _resolve_destination_tables(form, mock_remote_api)


class TestResolveDestinationHostAndDb:
    """Test _resolve_destination_host_and_db across all branches and edge cases."""

    @pytest.mark.asyncio
    async def test_dest_service_id_resolves_host_and_port(
        self, created_service, mock_remote_api
    ):
        """dest_service_id set: fetch and return host and port."""
        created_service.port = 3307
        mock_remote_api.get = AsyncMock(side_effect=[created_service.model_dump()])
        form = _make_form_with_source_ids(
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_host=None,
            dest_port=None,
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {
            "dest_host": created_service.node.address,
            "dest_port": 3307,
        }
        assert mock_remote_api.get.call_count == 1

    @pytest.mark.asyncio
    async def test_dest_service_port_none_uses_default(
        self, created_node, mock_remote_api
    ):
        """dest_service.port=None: use DEFAULT_MYSQL_PORT fallback."""
        dest_service = CreatedServiceFactory.build(
            node=created_node, type=ServiceTypeEnum.MYSQL, port=None
        )
        mock_remote_api.get = AsyncMock(side_effect=[dest_service.model_dump()])
        form = _make_form_with_source_ids(
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_host=None,
            dest_port=None,
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {
            "dest_host": dest_service.node.address,
            "dest_port": DEFAULT_MYSQL_PORT,
        }

    @pytest.mark.asyncio
    async def test_manual_host_with_port(self, mock_remote_api):
        """Manual dest_host and dest_port: no API calls."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None, dest_host="archive.host", dest_port=3307
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {"dest_host": "archive.host", "dest_port": 3307}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_manual_host_without_port_defaults_to_mysql_port(
        self, mock_remote_api
    ):
        """Manual dest_host, no dest_port: dest_port defaults to ``DEFAULT_MYSQL_PORT``.

        Without this default, an omitted ``DEST_PORT`` falls through to the
        payload script's ``dst_port = src_port`` fallback, which would
        silently route the archive to whatever port the source uses instead
        of MySQL's default. See ``app/sep/plugins/archives/payload``.
        """
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None, dest_host="archive.host", dest_port=None
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {
            "dest_host": "archive.host",
            "dest_port": DEFAULT_MYSQL_PORT,
        }
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_host_fields_set(self, mock_remote_api):
        """No host fields set: empty dict from host section."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None, dest_host=None, dest_port=None, dest_db_name=""
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_dest_service_and_db_id_fully_resolved(
        self, created_service, created_schema, mock_remote_api
    ):
        """dest_service_id + dest_db_id: fetch both, return all three keys."""
        created_service.port = 3307
        mock_remote_api.get = AsyncMock(
            side_effect=[created_service.model_dump(), created_schema.model_dump()]
        )
        form = _make_form_with_source_ids(
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_db_id=MOCK_CREATED_SCHEMA_ID,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {
            "dest_host": created_service.node.address,
            "dest_port": 3307,
            "dest_db": created_schema.name,
        }
        assert mock_remote_api.get.call_count == EXPECTED_API_CALLS_FOR_BOTH_IDS

    @pytest.mark.asyncio
    async def test_dest_service_and_db_name(self, created_service, mock_remote_api):
        """dest_service_id + dest_db_name (no ID): fetch service, use manual db name."""
        created_service.port = 3307
        mock_remote_api.get = AsyncMock(side_effect=[created_service.model_dump()])
        form = _make_form_with_source_ids(
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_db_id=None,
            dest_db_name="archive_db",
            dest_host=None,
            dest_port=None,
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {
            "dest_host": created_service.node.address,
            "dest_port": 3307,
            "dest_db": "archive_db",
        }
        assert mock_remote_api.get.call_count == 1

    @pytest.mark.asyncio
    async def test_manual_host_and_db_name(self, mock_remote_api):
        """Manual host and db_name (no IDs): no API calls."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None,
            dest_host="archive.host",
            dest_port=3307,
            dest_db_id=None,
            dest_db_name="archive_db",
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {
            "dest_host": "archive.host",
            "dest_port": 3307,
            "dest_db": "archive_db",
        }
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_manual_db_name_only(self, mock_remote_api):
        """Manual dest_db_name only (no host, no ID): no API calls."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_id=None,
            dest_db_name="mydb",
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {"dest_db": "mydb"}
        assert "dest_host" not in result
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_whitespace_db_name_returns_no_db_key(self, mock_remote_api):
        """dest_db_name with whitespace rstrips to empty: no dest_db key."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_id=None,
            dest_db_name="   ",
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {}
        assert "dest_db" not in result
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_all_none_returns_empty(self, mock_remote_api):
        """All dest host and db fields None/blank: empty dict."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_id=None,
            dest_db_name="",
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {}
        mock_remote_api.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_dest_service_not_found_propagates_exception(self, mock_remote_api):
        """Service fetch raises HTTPNotFoundException: propagates."""
        mock_remote_api.get = AsyncMock(side_effect=HTTPNotFoundException())
        form = _make_form_with_source_ids(
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_host=None,
            dest_port=None,
        )

        with pytest.raises(HTTPNotFoundException):
            await _resolve_destination_host_and_db(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_dest_schema_not_found_propagates_exception(
        self, created_service, mock_remote_api
    ):
        """Service fetch succeeds, schema fetch raises HTTPNotFoundException."""
        mock_remote_api.get = AsyncMock(
            side_effect=[created_service.model_dump(), HTTPNotFoundException()]
        )
        form = _make_form_with_source_ids(
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_db_id=MOCK_CREATED_SCHEMA_ID,
            dest_host=None,
            dest_port=None,
        )

        with pytest.raises(HTTPNotFoundException):
            await _resolve_destination_host_and_db(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_whitespace_dest_host_returns_empty(self, mock_remote_api):
        """Whitespace-only dest_host strips to empty: no dest_host key returned."""
        mock_remote_api.get = AsyncMock()
        form = _make_form_with_source_ids(
            dest_service_id=None,
            dest_host="   ",
            dest_port=None,
            dest_db_id=None,
            dest_db_name="",
        )

        result = await _resolve_destination_host_and_db(form, mock_remote_api)

        assert result == {}
        assert "dest_host" not in result
        mock_remote_api.get.assert_not_called()


class TestBuildArchivesPayloadSelfArchiveGuard:
    """Tests for the post-resolution self-archive guard in ``_build_archives_payload``."""

    @pytest.mark.asyncio
    async def test_dest_db_id_resolves_to_same_schema_raises(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Case 1: dest_db_id resolves to source schema name on the same service+table."""
        dest_table_same_name = CreatedTableFactory.build()
        dest_table_same_name.id = MOCK_DESTINATION_TABLE_ID
        dest_table_same_name.name = created_table.name

        form = ArchivesCreate(
            alias="self-archive-case1",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=MOCK_DESTINATION_TABLE_ID,
            dest_table_name="",
            dest_file=None,
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_db_id=MOCK_CREATED_SCHEMA_ID,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
                dest_table_same_name.model_dump(),
                created_service.model_dump(),
                created_schema.model_dump(),
            ]
        )

        with pytest.raises(HTTPUnprocessableEntityException):
            await _build_archives_payload(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_whitespace_dest_host_and_db_same_table_raises(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Case 2: whitespace dest_host + dest_db_name strip to empty, same table name."""
        form = ArchivesCreate(
            alias="self-archive-case2",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=None,
            dest_table_name=created_table.name,
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host="   ",
            dest_port=None,
            dest_db_name="   ",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )

        with pytest.raises(HTTPUnprocessableEntityException):
            await _build_archives_payload(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_whitespace_dest_service_and_db_name_same_table_raises(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Case 2b: dest_service_id same + whitespace dest_db_name + same table name."""
        dest_table_same_name = CreatedTableFactory.build()
        dest_table_same_name.id = MOCK_DESTINATION_TABLE_ID
        dest_table_same_name.name = created_table.name

        form = ArchivesCreate(
            alias="self-archive-case2b",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=MOCK_DESTINATION_TABLE_ID,
            dest_table_name="",
            dest_file=None,
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_db_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_name="   ",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
                dest_table_same_name.model_dump(),
                created_service.model_dump(),
            ]
        )

        with pytest.raises(HTTPUnprocessableEntityException):
            await _build_archives_payload(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_different_dest_host_not_rejected(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Different dest_host: same table name is fine — genuinely different archive."""
        form = ArchivesCreate(
            alias="cross-host-archive",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=None,
            dest_table_name=created_table.name,
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host="other.host",
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )

        result = await _build_archives_payload(form, mock_remote_api)

        assert isinstance(result, TaskWrite)

    @pytest.mark.asyncio
    async def test_dest_db_id_resolves_to_different_schema_not_rejected(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """dest_db_id resolves to a different schema name: no self-archive."""
        different_schema = CreatedSchemaFactory.build()
        different_schema.name = created_schema.name + "_archive"

        dest_table_same_name = CreatedTableFactory.build()
        dest_table_same_name.id = MOCK_DESTINATION_TABLE_ID
        dest_table_same_name.name = created_table.name

        form = ArchivesCreate(
            alias="cross-schema-archive",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=MOCK_DESTINATION_TABLE_ID,
            dest_table_name="",
            dest_file=None,
            dest_service_id=MOCK_CREATED_SERVICE_ID,
            dest_db_id=MOCK_CREATED_SCHEMA_ID,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
                dest_table_same_name.model_dump(),
                created_service.model_dump(),
                different_schema.model_dump(),
            ]
        )

        result = await _build_archives_payload(form, mock_remote_api)

        assert isinstance(result, TaskWrite)

    @pytest.mark.asyncio
    async def test_file_destination_skips_self_archive_check(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """File destination: no table comparison, never a self-archive."""
        form = ArchivesCreate(
            alias="file-archive",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=None,
            dest_table_name="",
            dest_file="/tmp/archive.csv",
            dest_service_id=None,
            dest_db_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )

        result = await _build_archives_payload(form, mock_remote_api)

        assert isinstance(result, TaskWrite)

    @pytest.mark.asyncio
    async def test_same_host_different_port_not_rejected(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Same hostname but different port: two distinct MySQL instances, not a self-archive."""
        created_service.port = DEFAULT_MYSQL_PORT

        form = ArchivesCreate(
            alias="cross-port-archive",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=None,
            dest_table_name=created_table.name,
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host=created_service.node.address,
            dest_port=DEFAULT_MYSQL_PORT + 1,
            dest_db_name=created_schema.name,
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )

        result = await _build_archives_payload(form, mock_remote_api)

        assert isinstance(result, TaskWrite)

    @pytest.mark.asyncio
    async def test_source_by_id_manual_dest_table_name_raises(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Source resolved by inventory ID, dest table as manual name: guard still fires."""
        form = ArchivesCreate(
            alias="self-archive-id-src-name-dst",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=None,
            dest_table_name=created_table.name,
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )

        with pytest.raises(HTTPUnprocessableEntityException):
            await _build_archives_payload(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_manual_source_names_dest_table_id_raises(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Source as manual names, dest table resolved by inventory ID: guard still fires."""
        dest_table_same_name = CreatedTableFactory.build()
        dest_table_same_name.id = MOCK_DESTINATION_TABLE_ID
        dest_table_same_name.name = created_table.name

        form = ArchivesCreate(
            alias="self-archive-name-src-id-dst",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=None,
            source_table_id=None,
            source_db_name=created_schema.name,
            source_table_name=created_table.name,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=MOCK_DESTINATION_TABLE_ID,
            dest_table_name="",
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                dest_table_same_name.model_dump(),
            ]
        )

        with pytest.raises(HTTPUnprocessableEntityException):
            await _build_archives_payload(form, mock_remote_api)

    @pytest.mark.asyncio
    async def test_mixed_case_table_name_not_rejected(
        self, created_service, created_schema, created_table, mock_remote_api
    ):
        """Mixed-case dest_table_name is distinct on case-sensitive servers.

        The guard uses exact match (like Validator 1b), so ``foo``/``FOO`` is accepted.
        """
        created_table.name = "archive_tbl"

        form = ArchivesCreate(
            alias="mixed-case-dest-table",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=MOCK_CREATED_SCHEMA_ID,
            source_table_id=MOCK_CREATED_TABLE_ID,
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=None,
            dest_table_name=created_table.name.upper(),
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                created_schema.model_dump(),
                created_table.model_dump(),
            ]
        )

        result = await _build_archives_payload(form, mock_remote_api)

        assert isinstance(result, TaskWrite)

    @pytest.mark.asyncio
    async def test_source_query_path_skips_self_archive_check(
        self, created_service, mock_remote_api
    ):
        """source_query path: no source table resolved, check is skipped."""
        dest_table_obj = CreatedTableFactory.build()
        dest_table_obj.id = MOCK_DESTINATION_TABLE_ID

        form = ArchivesCreate(
            alias="source-query-archive",
            hostname="localhost",
            service_id=MOCK_CREATED_SERVICE_ID,
            source_db_id=None,
            source_table_id=None,
            source_db_name="",
            source_table_name="",
            source_query="SELECT id FROM foo WHERE id > 1",
            swap_drop=SwapDropEnum.PURGE_ONLY,
            where="id > 1",
            dest_table_id=MOCK_DESTINATION_TABLE_ID,
            dest_table_name="",
            dest_file=None,
            dest_service_id=None,
            dest_db_id=None,
            dest_host=None,
            dest_port=None,
            dest_db_name="",
        )
        mock_remote_api.get = AsyncMock(
            side_effect=[
                created_service.model_dump(),
                dest_table_obj.model_dump(),
            ]
        )

        result = await _build_archives_payload(form, mock_remote_api)

        assert isinstance(result, TaskWrite)

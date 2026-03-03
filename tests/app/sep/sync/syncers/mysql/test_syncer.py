# Copyright 2026 Percona LLC
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

"""Test the app.sep.sync.syncers.mysql.syncer module."""

import gzip
import json
from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest

from app.inventory.models import ServiceTypeEnum
from app.sep.inventory import (
    CreatedNode,
    CreatedSchema,
    CreatedService,
    CreatedTable,
    Node,
    Service,
    Table,
)
from app.sep.sync.models import TaskRunResult
from app.sep.sync.syncers.mysql.syncer import (
    _MySQLSyncResultEntityTypeEnum,
    MySQLSchema,
    MySQLService,
    MySQLSyncer,
)
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
    MOCK_CREATED_NODE_ID,
)


@pytest.fixture
def mock_mysql_syncer(mock_remote_api) -> MySQLSyncer:
    """Test fixture: return a MySQLSyncer with mocked APIs."""
    return MySQLSyncer(tasks_api=mock_remote_api, inventory_api=mock_remote_api)


@pytest.fixture
def created_service() -> CreatedService:
    """Test fixture: return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.node_id = MOCK_CREATED_NODE_ID
    created_service.type = ServiceTypeEnum.MYSQL
    created_service.node = CreatedNode(
        address="localhost", id=MOCK_CREATED_NODE_ID, node_name="localhost"
    )
    created_service.port = 8000
    return created_service


@pytest.fixture
def created_node(created_service) -> CreatedNode:
    """Test fixture: return a fake created node."""
    created_node = CreatedNodeFactory.build()
    created_node.address = "localhost:8000"
    created_node.services = [created_service]
    return created_node


@pytest.fixture
def created_schema(created_service) -> CreatedSchema:
    """Test fixture: return a fake created schema."""
    created_schema = CreatedSchemaFactory.build(name="test_schema")
    created_schema.service = created_service
    return created_schema


@pytest.fixture
def created_table(created_schema) -> CreatedTable:
    """Test fixture: return a fake created table."""
    created_table = CreatedTableFactory.build(name="test_table")
    created_table.database = created_schema
    return created_table


class TestConfigAndTargets:
    """Test script config building and target resolution."""

    @pytest.mark.asyncio
    async def test_build_script_config(self, mock_mysql_syncer):
        """Test building script config with schema and table."""
        cfg = mock_mysql_syncer.build_script_config(
            "127.0.0.1", "192.168.1.10", schema="test_schema", table="test_table"
        )
        data = json.loads(cfg)
        assert data["hosts"] == ["127.0.0.1", "192.168.1.10"]
        assert data["ignore_schemas"] == []
        assert data["resolve_localhost"] is True
        assert data["schema"] == "test_schema"
        assert data["table"] == "test_table"

    @pytest.mark.asyncio
    async def test_get_task_target(self, mock_mysql_syncer):
        """Test resolving forced executor host as target."""
        mock_mysql_syncer.force_executor_host = "some_executor_host"
        target = await mock_mysql_syncer.get_task_target("127.0.0.1")
        assert target == "some_executor_host"

    def test_payload_path_points_to_payload_py(self, mock_mysql_syncer):
        """Test payload_path returns payload.py path."""
        p = mock_mysql_syncer.payload_path
        assert p.name == "payload.py"
        assert str(p).endswith("/payload.py")

    def test_build_entity_address_service_only(self):
        """Test returning service address when only service is provided."""
        addr = MySQLSyncer._build_entity_address("host:3306")
        assert addr == "host:3306"


class TestFetchMethods:
    """Test fetch methods for node, service, schema, and table."""

    @pytest.mark.asyncio
    async def test_fetch_node(self, created_node, mock_mysql_syncer, mocker):
        """Test fetching node with services index."""
        mocker.patch.object(
            MySQLSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {"localhost:8000": "hostname"}
        services_manifest = {
            _MySQLSyncResultEntityTypeEnum.SERVICES: {
                "localhost:8000": {
                    "schemas_path": "out/schemas.ndjson.gz",
                    "schemas_count": 1,
                }
            }
        }
        mocker.patch.object(
            MySQLSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(123, json.dumps(services_manifest))
        updated_node = await mock_mysql_syncer.fetch_node(created_node)
        assert isinstance(updated_node, Node)
        assert len(updated_node.services) == 1
        assert isinstance(updated_node.services[0], Service)

    @pytest.mark.asyncio
    async def test_fetch_service(
        self, created_node, created_service, mock_mysql_syncer, mocker
    ):
        """Test fetching service to return schemas index iterator."""
        mocker.patch.object(
            MySQLSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {"localhost:8000": "hostname"}
        services_manifest = {
            _MySQLSyncResultEntityTypeEnum.SERVICES: {
                "localhost:8000": {
                    "schemas_path": "out/localhost%3A8000/schemas.ndjson.gz",
                    "schemas_count": 1,
                }
            }
        }
        mocker.patch.object(
            MySQLSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(456, json.dumps(services_manifest))
        updated_service = await mock_mysql_syncer.fetch_service(created_service)
        assert isinstance(updated_service, MySQLService)
        assert updated_service.schemas_index is not None

    @pytest.mark.asyncio
    async def test_fetch_schema(self, created_schema, mock_mysql_syncer, mocker):
        """Test fetching schema to return tables iterator."""
        mocker.patch.object(
            MySQLSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {"localhost:8000": "hostname"}
        schema_address = "localhost:8000/test_schema"
        schemas_manifest = {
            _MySQLSyncResultEntityTypeEnum.SCHEMAS: {
                schema_address: {
                    "tables_path": "out/localhost%3A8000/test_schema_tables.ndjson.gz",
                    "tables_count": 1,
                }
            }
        }
        mocker.patch.object(
            MySQLSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(789, json.dumps(schemas_manifest))
        updated_schema = await mock_mysql_syncer.fetch_schema(created_schema)
        assert isinstance(updated_schema, MySQLSchema)
        assert updated_schema.tables_aiter is not None

    @pytest.mark.asyncio
    async def test_fetch_table(self, created_table, mock_mysql_syncer, mocker):
        """Test fetching table from tables payload."""
        mocker.patch.object(
            MySQLSyncer, "get_available_hosts", new_callable=AsyncMock
        ).return_value = {"localhost:8000": "hostname"}
        table_key = f"localhost:8000/{created_table.database.name}.{created_table.name}"
        payload = {
            _MySQLSyncResultEntityTypeEnum.TABLES: {
                table_key: {
                    "name": created_table.name,
                    "create": "CREATE TABLE users (id INT PRIMARY KEY, name VARCHAR(50))",
                    "keys": {
                        "PRIMARY": {
                            "columns": ["id"],
                            "unique": True,
                            "nullable": False,
                        }
                    },
                }
            }
        }
        mocker.patch.object(
            MySQLSyncer, "wait_for_task_output", new_callable=AsyncMock
        ).return_value = TaskRunResult(321, json.dumps(payload))
        updated_table = await mock_mysql_syncer.fetch_table(created_table)
        assert isinstance(updated_table, Table)
        assert updated_table.name == created_table.name

    @pytest.mark.asyncio
    async def test_fetch_service_uses_cached_fetch_result(
        self, created_service, mock_mysql_syncer
    ):
        """Test using cached fetch result for service."""
        mock_mysql_syncer._inventory_index_cache[
            _MySQLSyncResultEntityTypeEnum.SERVICES
        ][created_service.address] = (
            999,
            {"schemas_path": "out/schemas.ndjson.gz", "schemas_count": 1},
        )
        svc = await mock_mysql_syncer.fetch_service(created_service)
        assert isinstance(svc, MySQLService)
        assert svc.schemas_index is not None

    @pytest.mark.asyncio
    async def test_fetch_schema_uses_cached_fetch_result(
        self, created_schema, mock_mysql_syncer
    ):
        """Test using cached fetch result for schema."""
        addr = f"{created_schema.service.address}/{created_schema.name}"
        mock_mysql_syncer._inventory_index_cache[
            _MySQLSyncResultEntityTypeEnum.SCHEMAS
        ][addr] = (
            222,
            {"tables_path": "out/tables.ndjson.gz", "tables_count": 1},
        )
        sch = await mock_mysql_syncer.fetch_schema(created_schema)
        assert isinstance(sch, MySQLSchema)
        assert sch.tables_aiter is not None


class TestPerformMethods:
    """Test perform methods for node, service, schema, and table."""

    @pytest.mark.asyncio
    async def test_perform_node_sync(self, created_node, mock_mysql_syncer, mocker):
        """Test performing node sync with two services on same port."""
        expected_sync_service_await_count = 2
        updated_node = created_node.model_copy()
        updated_node.services = created_node.services.copy()
        updated_node.services.append(
            CreatedService(
                id=created_node.services[0].id + 1,
                node_id=created_node.services[0].node_id,
                type=ServiceTypeEnum.MYSQL,
                port=created_node.services[0].port,
                name="extra-service",
            )
        )
        sync_service = mocker.patch.object(
            MySQLSyncer, "sync_service", new_callable=AsyncMock
        )
        await mock_mysql_syncer.perform_node_sync(created_node, updated_node)
        assert sync_service.await_count == expected_sync_service_await_count
        sync_service.assert_any_await(created_node.services[0])

    @pytest.mark.asyncio
    async def test_perform_service_sync_sets_schema_cache(
        self,
        created_service,
        created_schema,
        mock_remote_api,
        mock_mysql_syncer,
        mocker,
    ):
        """Test setting schema cache while streaming schemas."""
        schema_data = created_schema.model_dump()
        mock_mysql_syncer._inventory_index_cache[
            _MySQLSyncResultEntityTypeEnum.SERVICES
        ][created_service.address] = (111, {"schemas_path": "p", "schemas_count": 1})
        mock_remote_api.post.side_effect = [schema_data]
        mocker.patch.object(
            MySQLSyncer, "get_inventory_service_schemas", return_value=[]
        )

        async def schemas_idx():
            yield schema_data

        updated = MySQLService.model_validate(
            created_service.model_dump(exclude={"schemas"})
        )
        updated.schemas_index = schemas_idx()
        mocker.patch.object(MySQLSyncer, "sync_schema", new_callable=AsyncMock)
        await mock_mysql_syncer.perform_service_sync(created_service, updated)
        addr = f"{created_service.address}/test_schema"
        assert (
            addr
            in mock_mysql_syncer._inventory_index_cache[
                _MySQLSyncResultEntityTypeEnum.SCHEMAS
            ]
        )

    @pytest.mark.asyncio
    async def test_perform_schema_sync(
        self, created_schema, created_table, mock_remote_api, mock_mysql_syncer, mocker
    ):
        """Test performing schema sync while streaming tables."""
        updated_schema = created_schema.model_copy()
        table_data = created_table.model_dump()
        mock_remote_api.put.side_effect = [updated_schema.model_dump()]
        mock_remote_api.post.side_effect = [table_data]

        async def tables_iter() -> AsyncGenerator[dict, None]:
            yield table_data

        mysql_schema = MySQLSchema.model_validate(
            created_schema.model_dump(exclude={"tables"})
            | {"address": "localhost:8000/test_schema"}
        )
        mysql_schema.tables_aiter = tables_iter()
        sync_table = mocker.patch.object(
            MySQLSyncer, "sync_table", new_callable=AsyncMock
        )
        delete_table = mocker.patch.object(
            MySQLSyncer, "delete_table", new_callable=AsyncMock
        )
        await mock_mysql_syncer.perform_schema_sync(created_schema, mysql_schema)
        sync_table.assert_awaited()
        delete_table.assert_awaited()

    @pytest.mark.asyncio
    async def test_perform_table_sync_calls_update(
        self, created_table, mock_mysql_syncer, mocker
    ):
        """Test performing table sync which updates the table."""
        updated = Table(name=created_table.name, create="CREATE TABLE x()")
        upd = mocker.patch.object(MySQLSyncer, "update_table", new_callable=AsyncMock)
        await mock_mysql_syncer.perform_table_sync(created_table, updated)
        upd.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_perform_inventory_sync_invokes_sync_node(
        self, mock_mysql_syncer, mocker
    ):
        """Test performing inventory sync by iterating nodes."""
        node = CreatedNodeFactory.build()
        mocker.patch.object(MySQLSyncer, "get_inventory_nodes", return_value=[node])
        sync_node_mock = mocker.patch.object(
            MySQLSyncer, "sync_node", new_callable=AsyncMock
        )
        await mock_mysql_syncer.perform_inventory_sync()
        sync_node_mock.assert_awaited_once_with(node)


class TestStreamsAndParsing:
    """Test gzip line iteration and NDJSON streaming."""

    def test_split_lines_from_buffer_variants(self, mock_mysql_syncer):
        """Test splitting lines from buffer with tail handling."""
        buf = bytearray()
        data1 = b"one\ntwo\nthr"
        data2 = b"ee\n"
        got = list(MySQLSyncer._split_lines_from_buffer(buf, data1, "utf-8"))
        assert got == ["one", "two"]
        got2 = list(MySQLSyncer._split_lines_from_buffer(buf, data2, "utf-8"))
        assert got2 == ["three"]
        assert buf == bytearray()

    @pytest.mark.asyncio
    async def test_iter_lines_gzip_stream_chunks(self, mock_mysql_syncer):
        """Test iterating gzip stream lines across chunks."""
        ndjson = b"a\nb\nc"
        comp = gzip.compress(ndjson, mtime=0)

        async def chunks():
            yield comp[:7]
            yield comp[7:13]
            yield comp[13:]

        got = [
            line async for line in mock_mysql_syncer._iter_lines_gzip_stream(chunks())
        ]
        assert got == ["a", "b", "c"]

    @pytest.mark.asyncio
    async def test_iter_lines_gzip_stream_uses_remaining_flush(
        self, mock_mysql_syncer, mocker
    ):
        """Test yielding lines from remaining bytes produced by flush()."""

        class DummyDecompressor:
            def decompress(self, _data):
                return b""

            def flush(self):
                return b"l1\nl2\n"

        mocker.patch(
            "app.sep.sync.syncers.mysql.syncer.zlib.decompressobj",
            return_value=DummyDecompressor(),
        )

        async def chunks():
            yield b"ignored-1"
            yield b"ignored-2"

        lines = [
            line async for line in mock_mysql_syncer._iter_lines_gzip_stream(chunks())
        ]

        assert lines == ["l1", "l2"]

    @pytest.mark.asyncio
    async def test_stream_ndjson_file_with_bad_line(self, mock_mysql_syncer, mocker):
        """Test streaming NDJSON and skipping invalid line."""
        ndjson = b'{"x":1}\nthis-is-not-json\n'
        comp = gzip.compress(ndjson, mtime=0)

        async def fake_stream(_url, params=None):
            yield comp[:10]
            yield comp[10:]

        mocker.patch.object(
            mock_mysql_syncer.tasks_api, "stream", return_value=fake_stream("", {})
        )
        out = [obj async for obj in mock_mysql_syncer.stream_ndjson_file(1, "x.gz")]
        assert out == [{"x": 1}]

    @pytest.mark.asyncio
    async def test_wait_for_task_output_default_payload(
        self, mock_mysql_syncer, mocker
    ):
        """Test using default file payload and delegating to super."""

        async def fake_super(_, *args, **kwargs):
            return TaskRunResult(1, "{}")

        mocker.patch(
            "app.sep.sync.models.BaseTaskSyncer.wait_for_task_output",
            side_effect=fake_super,
        )
        res = await mock_mysql_syncer.wait_for_task_output(config="{}", target="host")
        assert isinstance(res, TaskRunResult)


class TestModelIteratorsAndGuards:
    """Test model iterators and sync guards."""

    @pytest.mark.asyncio
    async def test_mysqlservice_empty_iterator_when_none(self, created_service):
        """Test iterating empty schemas_index when unset."""
        svc = MySQLService.model_validate(
            created_service.model_dump(exclude={"schemas"})
        )
        out = [item async for item in svc.schemas_index]
        assert out == []

    @pytest.mark.asyncio
    async def test_mysqlschema_iter_tables_fallback(
        self, created_schema, created_table
    ):
        """Test iterating existing tables when no async iterator set."""
        sch = MySQLSchema.model_validate(
            created_schema.model_dump(exclude={"tables"})
            | {"address": "localhost:8000/s"}
        )
        sch.tables = [created_table]
        out = [table async for table in sch.iter_tables()]

        assert len(out) == 1
        assert out[0].name == "test_table"

    def test_can_sync_node_true_false(self, mock_mysql_syncer):
        """Test returning True only when node has a MySQL service."""
        node_with_mysql = Node(
            address="x",
            name="x",
            services=[Service(type=ServiceTypeEnum.MYSQL, port=3306, name="s")],
        )
        node_without_mysql = Node(address="y", name="y", services=[])
        assert mock_mysql_syncer.can_sync_node(node_with_mysql) is True
        assert mock_mysql_syncer.can_sync_node(node_without_mysql) is False

"""Implement the MySQL Inventory Sync."""

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, ClassVar

from async_lru import alru_cache

from app.inventory.models import ServiceTypeEnum
from app.sep.inventory import (
    CreatedNode,
    CreatedSchema,
    CreatedService,
    CreatedTable,
    Node,
    Schema,
    Service,
    Table,
)
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.models import BaseTaskSyncer

logger = logging.getLogger(__name__)


class MySQLSyncer(BaseTaskSyncer):
    """Synchronize MySQL inventory entities within the SEP application.

    The `MySQLSyncer` class extends `BaseTaskSyncer` to provide synchronization
    capabilities specifically for MySQL services. It handles fetching and updating
    nodes, services, schemas, and tables from MySQL databases, ensuring that the
    inventory remains consistent with the source data.

    :cvar SYNC_TO_LIMIT: The highest entity type that can be synchronized. Set to
        `SyncInventoryEntityTypeEnum.TABLE`.
    :vartype SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum]
    :param ignore_schemas: A list of schema names to ignore during synchronization.
    :type ignore_schemas: list[str]
    :param resolve_localhost: Resolve the --host IP to 127.0.0.1 if it's the same as
        the executor host. Defaults to True.
    :type resolve_localhost: bool
    """

    SYNC_TO_LIMIT: ClassVar[SyncInventoryEntityTypeEnum] = (
        SyncInventoryEntityTypeEnum.TABLE
    )
    ignore_schemas: list[str] = []
    resolve_localhost: bool = True

    @property
    def payload_path(self) -> Path:
        """Determine the path to the payload script.

        This property constructs the file path to the `payload.py` script, which is
        used for executing synchronization tasks.

        :return: The `Path` object pointing to the payload script.
        :rtype: Path
        """
        # TODO: Create PAYLOADS_DIR setting and keep payloads/scripts there  # noqa: TD002, TD003
        return Path(__file__).parent / "payload.py"

    @alru_cache
    async def get_task_target(self, host: str) -> str:
        """Return the target host for the task from the host.

        This method returns `self.force_executor_host` if set. Otherwise, it tries to
        find a target with the same address as `host`. If it can't, the first available
        host is returned.

        :param host: The target host.
        :type host: str
        :return: The target host for the task.
        :rtype: str
        """
        if self.force_executor_host:
            return self.force_executor_host
        available_hosts = await self.get_available_hosts()
        return available_hosts.get(host, next(iter(available_hosts.values())))

    def build_script_config(
        self,
        *hosts: str,
        schema: str | None = None,
        table: str | None = None,
    ) -> str:
        """Build the configuration for the MySQL sync script.

        Constructs a JSON configuration based on the provided hosts,
        schema, table, and any schemas to ignore.

        :param hosts: Variable length argument list of host addresses.
        :type hosts: str
        :param schema: The name of the schema to synchronize. Defaults to `None`.
        :type schema: str | None
        :param table: The name of the table to synchronize. Defaults to `None`.
        :type table: str | None
        :return: A JSON string containing configuration for the script.
        :rtype: str
        """
        config = {
            "hosts": hosts,
            "ignore_schemas": self.ignore_schemas,
            "resolve_localhost": self.resolve_localhost,
        }
        if schema:
            config["schema"] = schema
        if table:
            config["table"] = table
        return json.dumps(config)

    async def build_meta(self, config: str, target: str) -> dict[str, str]:
        """Build metadata for task execution.

        Creates a metadata dictionary containing the command-line arguments, target
        information, and required dependencies for the synchronization task.

        :param config: The configuration for the task script.
        :type config: str
        :param target: The target host for the task.
        :type target: str
        :return: A dictionary with metadata required for task execution.
        :rtype: dict[str, str]
        """
        # TODO: Figure out a way to keep requirements attached to payloads  # noqa: TD002, TD003
        return {
            "config": config,
            "target": target,
            "requirements": ["PyMySQL", "PyMySQL[rsa]"],
        }

    async def wait_for_task_output(
        self,
        task_name: str = "run-python",
        stdout_step: str = "run-script",
        payload: str | None = None,
        **meta: Any,
    ) -> str:
        """Wait for a task to complete and retrieve its output.

        Override `BaseTaskSyncer.wait_for_task_output` to provide default arguments.

        :param task_name: The name of the task to execute. Defaults to `"run-python"`.
        :type task_name: str
        :param stdout_step: The step identifier for stdout retrieval. Defaults to
            `"run-script"`.
        :type stdout_step: str
        :param payload: The payload to send with the task execution request.
            Defaults to `None`. If None, the `payload_path` is used.
        :type payload: str | None
        :param meta: Additional meta variables to send with the task execution request.
        :type meta: Any
        :return: The output from the task's stdout.
        :rtype: str
        :raises ValueError: If the task fails or times out.
        """
        payload = f"file://{self.payload_path}" if payload is None else payload
        return await super().wait_for_task_output(
            task_name,
            stdout_step,
            payload,
            **meta,
        )

    async def perform_inventory_sync(self) -> None:
        """Execute the inventory synchronization process.

        Initiates synchronization for all available inventory nodes by iterating
        through each node and invoking the `sync_node` method.
        """
        for node in await self.get_inventory_nodes():
            await self.sync_node(node)

    # TODO: Fail sync in case of MySQL connection error  # noqa: TD002, TD003
    async def fetch_node(self, created_node: CreatedNode) -> Node:
        """Fetch updated data for a specific node.

        Retrieves the latest information for the specified node by executing a
        synchronization task and processing the returned schema data.

        :param created_node: The node instance to fetch updated data for.
        :type created_node: CreatedNode
        :return: The updated node data.
        :rtype: Node
        """
        hosts = [
            service.address
            for service in created_node.services
            if self.can_sync_service(service)
        ]
        script_config = self.build_script_config(*hosts)
        meta = await self.build_meta(
            script_config,
            await self.get_task_target(created_node.address),
        )
        schemas_data = json.loads(await self.wait_for_task_output(**meta))
        services = []
        for created_service in created_node.services:
            if self.can_sync_service(created_service):
                service_data = created_service.model_dump(exclude={"schemas"})
                service_data["schemas"] = schemas_data.get(created_service.address, [])
                services.append(Service.model_validate(service_data))
        node = Node.model_validate(created_node.model_dump())
        node.services = services
        return node

    async def perform_node_sync(
        self,
        created_node: CreatedNode,
        updated_node: Node,
    ) -> None:
        """Synchronize data for a specific node.

        Updates the services associated with the node by comparing existing services
        with the updated services and performing necessary synchronization actions.

        :param created_node: The node instance to synchronize.
        :type created_node: CreatedNode
        :param updated_node: The updated node data.
        :type updated_node: Node
        """
        syncable_services = defaultdict(list)
        for service in created_node.services:
            syncable_services[service.port].append(service)
        for service in updated_node.services:
            for created_service in syncable_services[service.port]:
                await self.sync_service(created_service, service)

    async def fetch_service(self, created_service: CreatedService) -> Service:
        """Fetch updated data for a specific service.

        Retrieves the latest information for the specified service by executing a
        synchronization task and processing the returned schema data.

        :param created_service: The service instance to fetch updated data for.
        :type created_service: CreatedService
        :return: The updated service data.
        :rtype: Service
        """
        script_config = self.build_script_config(created_service.address)
        meta = await self.build_meta(
            script_config,
            await self.get_task_target(created_service.node.address),
        )
        schemas_data = json.loads(await self.wait_for_task_output(**meta))
        service_data = created_service.model_dump(exclude={"schemas"})
        service_data["schemas"] = schemas_data.get(created_service.address, [])
        return Service.model_validate(service_data)

    async def perform_service_sync(
        self,
        created_service: CreatedService,
        updated_service: Service,
    ) -> None:
        """Synchronize data for a specific service.

        Updates the schemas associated with the service by comparing existing schemas
        with the updated schemas and performing necessary synchronization actions.

        :param created_service: The service instance to synchronize.
        :type created_service: CreatedService
        :param updated_service: The updated service data.
        :type updated_service: Service
        """
        syncable_schemas = {}
        for schema in await self.get_inventory_service_schemas(created_service.id):
            syncable_schemas[schema.name] = schema
        for schema in updated_service.schemas:
            if (created_schema := syncable_schemas.pop(schema.name, None)) is None:
                logger.info("Creating new schema: %s", schema)
                created_schema = CreatedSchema.model_validate(
                    await self.inventory_api.post(
                        f"/services/{created_service.id}/schemas/",
                        json=schema.model_dump(),
                    ),
                )
            created_schema.service = created_service.model_copy(update={"schemas": []})
            await self.sync_schema(created_schema, schema)
        for schema in syncable_schemas.values():
            await self.delete_schema(schema)

    async def fetch_schema(self, created_schema: CreatedSchema) -> Schema:
        """Fetch updated data for a specific schema.

        Retrieves the latest information for the specified schema by executing a
        synchronization task and processing the returned table data.

        :param created_schema: The schema instance to fetch updated data for.
        :type created_schema: CreatedSchema
        :return: The updated schema data.
        :rtype: Schema
        """
        if (
            not (created_service := created_schema.service)
            or not created_service.address
        ):
            created_service = await self.get_inventory_service(
                created_schema.service_id,
            )
        host = created_service.address
        script_config = self.build_script_config(host, schema=created_schema.name)
        meta = await self.build_meta(
            script_config,
            await self.get_task_target(created_service.node.address),
        )
        schema_data = json.loads(await self.wait_for_task_output(**meta))
        return Schema.model_validate(schema_data)

    async def perform_schema_sync(
        self,
        created_schema: CreatedSchema,
        updated_schema: Schema,
    ) -> None:
        """Synchronize data for a specific schema.

        Updates the tables associated with the schema by comparing existing tables
        with the updated tables and performing necessary synchronization actions.

        :param created_schema: The schema instance to synchronize.
        :type created_schema: CreatedSchema
        :param updated_schema: The updated schema data.
        :type updated_schema: Schema
        """
        await self.update_schema(created_schema, updated_schema)
        syncable_tables = {}
        for table in created_schema.tables:
            syncable_tables[table.name] = table
        for table in updated_schema.tables:
            if (created_table := syncable_tables.pop(table.name, None)) is None:
                logger.info("Creating new table: %s", table)
                created_table = CreatedTable.model_validate(
                    await self.inventory_api.post(
                        f"/schemas/{created_schema.id}/tables/",
                        json=table.model_dump(),
                    ),
                )
                created_table.database = created_schema.model_copy(
                    update={"tables": []},
                )
            await self.sync_table(created_table, table)
        for table in syncable_tables.values():
            await self.delete_table(table)

    async def fetch_table(self, created_table: CreatedTable) -> Table:
        """Fetch updated data for a specific table.

        Retrieves the latest information for the specified table by executing a
        synchronization task.

        :param created_table: The table instance to fetch updated data for.
        :type created_table: CreatedTable
        :return: The updated table data.
        :rtype: Table
        """
        if (created_schema := created_table.database) and (
            created_service := created_schema.service
        ):
            if created_service.address:
                host = created_service.address
            else:
                created_service = await self.get_inventory_service(
                    created_service.id,
                )
                host = created_service.address
        else:
            created_schema = await self.get_inventory_schema(created_table.database_id)
            created_service = await self.get_inventory_service(
                created_schema.service_id,
            )
            host = created_service.address
        script_config = self.build_script_config(
            host,
            schema=created_table.database.name,
            table=created_table.name,
        )
        meta = await self.build_meta(
            script_config,
            await self.get_task_target(created_service.node.address),
        )
        table_data = json.loads(await self.wait_for_task_output(**meta))
        return Table.model_validate(table_data)

    async def perform_table_sync(
        self,
        created_table: CreatedTable,
        updated_table: Table,
    ) -> None:
        """Synchronize data for a specific table.

        Updates the table in the inventory system with the latest information.

        :param created_table: The table instance to synchronize.
        :type created_table: CreatedTable
        :param updated_table: The updated table data.
        :type updated_table: Table
        """
        await self.update_table(created_table, updated_table)

    @classmethod
    def can_sync_node(cls, node: CreatedNode) -> bool:
        """Determine if a specific node can be synchronized.

        Overrides the base method to check if the node has at least one MySQL service.

        :param node: The node instance to check.
        :type node: CreatedNode
        :return: `True` if the node can be synchronized, `False` otherwise.
        :rtype: bool
        """
        if super().can_sync_node(node):
            for service in node.services:
                if service.type == ServiceTypeEnum.MYSQL:
                    return True
        return False

    @classmethod
    def can_sync_service(cls, service: CreatedService) -> bool:
        """Determine if a specific service can be synchronized.

        Overrides the base method to check if the service is of type MySQL.

        :param service: The service instance to check.
        :type service: CreatedService
        :return: `True` if the service can be synchronized, `False` otherwise.
        :rtype: bool
        """
        return (
            super().can_sync_service(service) and service.type == ServiceTypeEnum.MYSQL
        )

    @classmethod
    def can_sync_schema(cls, schema: CreatedSchema) -> bool:
        """Determine if a specific schema can be synchronized.

        Overrides the base method to check if the schema belongs to a MySQL service.

        :param schema: The schema instance to check.
        :type schema: CreatedSchema
        :return: `True` if the schema can be synchronized, `False` otherwise.
        :rtype: bool
        """
        return (
            super().can_sync_schema(schema)
            and schema.service.type == ServiceTypeEnum.MYSQL
        )

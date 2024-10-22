"""Provide synchronization functions for the SEP inventory."""

from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.sync.models import BaseSyncer


async def run_inventory_sync(*syncers: BaseSyncer) -> None:
    """Execute inventory synchronization using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_inventory` method
    to perform inventory synchronization tasks asynchronously.

    :param syncers: One or more instances of `BaseSyncer` to perform inventory
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer in syncers:
        async with syncer as sync:
            await sync.sync_inventory()


async def run_node_sync(
    created_node: CreatedNode,
    *syncers: BaseSyncer,
) -> None:
    """Execute node synchronization for a created node using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_node` method
    with the specified `CreatedNode` to perform node synchronization tasks
    asynchronously.

    :param created_node: The node that has been created and needs to be synchronized.
    :type created_node: CreatedNode
    :param syncers: One or more instances of `BaseSyncer` to perform node
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer as sync:
            await sync.sync_node(created_node, refresh_at_start=bool(syncer_index))


async def run_service_sync(
    created_service: CreatedService,
    *syncers: BaseSyncer,
) -> None:
    """Execute service synchronization for a created service using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_service` method
    with the specified `CreatedService` to perform service synchronization tasks
    asynchronously.

    :param created_service: The service that has been created and needs to be
        synchronized.
    :type created_service: CreatedService
    :param syncers: One or more instances of `BaseSyncer` to perform service
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer as sync:
            await sync.sync_service(
                created_service,
                refresh_at_start=bool(syncer_index),
            )


async def run_schema_sync(
    created_schema: CreatedSchema,
    *syncers: BaseSyncer,
) -> None:
    """Execute schema synchronization for a created schema using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_schema` method
    with the specified `CreatedSchema` to perform schema synchronization tasks
    asynchronously.

    :param created_schema: The schema that has been created and needs to be
        synchronized.
    :type created_schema: CreatedSchema
    :param syncers: One or more instances of `BaseSyncer` to perform schema
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer as sync:
            await sync.sync_schema(created_schema, refresh_at_start=bool(syncer_index))


async def run_table_sync(
    created_table: CreatedTable,
    *syncers: BaseSyncer,
) -> None:
    """Execute table synchronization for a created table using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_table` method
    with the specified `CreatedTable` to perform table synchronization tasks
    asynchronously.

    :param created_table: The table that has been created and needs to be synchronized.
    :type created_table: CreatedTable
    :param syncers: One or more instances of `BaseSyncer` to perform table
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer as sync:
            await sync.sync_table(created_table, refresh_at_start=bool(syncer_index))

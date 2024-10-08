"""Provide synchronization functions for the SEP inventory."""

from app.sep.inventory import CreatedNode
from app.sep.inventory import CreatedSchema
from app.sep.inventory import CreatedService
from app.sep.inventory import CreatedTable
from app.sep.sync.models import BaseSyncer


async def run_inventory_sync(*syncers: BaseSyncer) -> None:
    """Execute inventory synchronization using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_inventory` method
    to perform inventory synchronization tasks asynchronously.

    Parameters
    ----------
    *syncers : BaseSyncer
        One or more instances of `BaseSyncer` to perform inventory synchronization.

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

    Parameters
    ----------
    created_node : CreatedNode
        The node that has been created and needs to be synchronized.
    *syncers : BaseSyncer
        One or more instances of `BaseSyncer` to perform node synchronization.

    """
    for syncer in syncers:
        async with syncer as sync:
            await sync.sync_node(created_node)


async def run_service_sync(
    created_service: CreatedService,
    *syncers: BaseSyncer,
) -> None:
    """Execute service synchronization for a created service using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_service` method
    with the specified `CreatedService` to perform service synchronization tasks
    asynchronously.

    Parameters
    ----------
    created_service : CreatedService
        The service that has been created and needs to be synchronized.
    *syncers : BaseSyncer
        One or more instances of `BaseSyncer` to perform service synchronization.

    """
    for syncer in syncers:
        async with syncer as sync:
            await sync.sync_service(created_service)


async def run_schema_sync(
    created_schema: CreatedSchema,
    *syncers: BaseSyncer,
) -> None:
    """Execute schema synchronization for a created schema using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_schema` method
    with the specified `CreatedSchema` to perform schema synchronization tasks
    asynchronously.

    Parameters
    ----------
    created_schema : CreatedSchema
        The schema that has been created and needs to be synchronized.
    *syncers : BaseSyncer
        One or more instances of `BaseSyncer` to perform schema synchronization.

    """
    for syncer in syncers:
        async with syncer as sync:
            await sync.sync_schema(created_schema)


async def run_table_sync(
    created_table: CreatedTable,
    *syncers: BaseSyncer,
) -> None:
    """Execute table synchronization for a created table using the provided syncers.

    Iterates over each `BaseSyncer` instance and invokes the `sync_table` method
    with the specified `CreatedTable` to perform table synchronization tasks
    asynchronously.

    Parameters
    ----------
    created_table : CreatedTable
        The table that has been created and needs to be synchronized.
    *syncers : BaseSyncer
        One or more instances of `BaseSyncer` to perform table synchronization.

    """
    for syncer in syncers:
        async with syncer as sync:
            await sync.sync_table(created_table)

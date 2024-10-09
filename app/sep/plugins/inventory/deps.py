"""Define dependencies for the Inventory plugin."""

from typing import Annotated

from fastapi import Depends

from app.core.utils import import_var
from app.sep.config import sep_settings
from app.sep.deps import InventoryAPI
from app.sep.deps import TaskAPI
from app.sep.inventory import CreatedNode
from app.sep.inventory import CreatedSchema
from app.sep.inventory import CreatedService
from app.sep.inventory import CreatedTable
from app.sep.sync.models import BaseSyncer


async def get_created_node(inventory_api: InventoryAPI, node_id: int) -> CreatedNode:
    """Retrieve a CreatedNode instance based on the given node ID.

    Fetches the node data from the Inventory API and validates it into a `CreatedNode`
    model.

    Parameters
    ----------
    inventory_api : InventoryAPI
        The API client used to interact with the inventory service.
    node_id : int
        The ID of the node to retrieve.

    Returns
    -------
    CreatedNode
        The validated `CreatedNode` instance.

    """
    return CreatedNode.model_validate(await inventory_api.get(f"/{node_id}"))


CreatedNodeDep = Annotated[CreatedNode, Depends(get_created_node)]


async def get_created_service(
    inventory_api: InventoryAPI,
    service_id: int,
) -> CreatedService:
    """Retrieve a CreatedService instance based on the given service ID.

    Fetches the service data from the Inventory API and validates it into a
    `CreatedService` model.

    Parameters
    ----------
    inventory_api : InventoryAPI
        The API client used to interact with the inventory service.
    service_id : int
        The ID of the service to retrieve.

    Returns
    -------
    CreatedService
        The validated `CreatedService` instance.

    """
    return CreatedService.model_validate(
        await inventory_api.get(f"/services/{service_id}"),
    )


CreatedServiceDep = Annotated[CreatedService, Depends(get_created_service)]


async def get_created_schema(
    inventory_api: InventoryAPI,
    schema_id: int,
) -> CreatedSchema:
    """Retrieve a CreatedSchema instance based on the given schema ID.

    Fetches the schema data from the Inventory API and validates it into a
    `CreatedSchema` model.

    Parameters
    ----------
    inventory_api : InventoryAPI
        The API client used to interact with the inventory service.
    schema_id : int
        The ID of the schema to retrieve.

    Returns
    -------
    CreatedSchema
        The validated `CreatedSchema` instance.

    """
    return CreatedSchema.model_validate(
        await inventory_api.get(f"/schemas/{schema_id}"),
    )


CreatedSchemaDep = Annotated[CreatedSchema, Depends(get_created_schema)]


async def get_created_table(inventory_api: InventoryAPI, table_id: int) -> CreatedTable:
    """Retrieve a CreatedTable instance based on the given table ID.

    Fetches the table data from the Inventory API and validates it into a `CreatedTable`
    model.

    Parameters
    ----------
    inventory_api : InventoryAPI
        The API client used to interact with the inventory service.
    table_id : int
        The ID of the table to retrieve.

    Returns
    -------
    CreatedTable
        The validated `CreatedTable` instance.

    """
    return CreatedTable.model_validate(await inventory_api.get(f"/tables/{table_id}"))


CreatedTableDep = Annotated[CreatedTable, Depends(get_created_table)]


def get_syncers(inventory_api: InventoryAPI, tasks_api: TaskAPI) -> list[BaseSyncer]:
    """Initialize and return a list of BaseSyncer instances based on configuration.

    Imports and initializes syncer classes as specified in the SEP settings, providing
    the necessary API clients and configuration parameters.

    Parameters
    ----------
    inventory_api : InventoryAPI
        The API client used to interact with the inventory service.
    tasks_api : TaskAPI
        The API client used to interact with the task service.

    Returns
    -------
    list[BaseSyncer]
        A list of initialized `BaseSyncer` instances.

    """
    syncers = []
    for sync_option in sep_settings.SYNCERS:
        syncer_class = import_var(sync_option.syncer)
        syncers.append(
            syncer_class(
                inventory_api=inventory_api,
                tasks_api=tasks_api,
                **sync_option.model_dump(exclude={"syncer"}),
            ),
        )
    return syncers


SyncersDep = Annotated[list[BaseSyncer], Depends(get_syncers)]

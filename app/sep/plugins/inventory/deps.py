"""Define dependencies for the Inventory plugin."""

from typing import Annotated

from fastapi import Depends
from pydantic import BaseModel

from app.core.utils import import_var
from app.inventory.models import SourceEnum
from app.sep.config import sep_settings
from app.sep.crud import SyncItemManager
from app.sep.deps import (
    CreatedNodeDep,
    CreatedSchemaDep,
    CreatedServiceDep,
    InventoryAPI,
    SessionDep,
    TaskAPI,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.sync.models import BaseSyncer


def get_syncers(inventory_api: InventoryAPI, tasks_api: TaskAPI) -> list[BaseSyncer]:
    """Initialize and return a list of BaseSyncer instances based on configuration.

    Imports and initializes syncer classes as specified in the SEP settings, providing
    the necessary API clients and configuration parameters.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryAPI
    :param tasks_api: The API client used to interact with the task service.
    :type tasks_api: TaskAPI
    :return: A list of initialized `BaseSyncer` instances.
    :rtype: list[BaseSyncer]
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


async def get_node_list_data(
    session: SessionDep, syncers: SyncersDep, inventory_api: InventoryAPI
) -> dict:
    """Assemble and return node list metadata for rendering or API response.

    Retrieves inventory data, enum definitions, sync status, and sync eligibility.

    :param session: Database session dependency.
    :type session: SessionDep
    :param syncers: List of initialized BaseSyncer instances.
    :type syncers: SyncersDep
    :param inventory_api: Inventory API client instance.
    :type inventory_api: InventoryAPI
    :return: A dictionary of context data used for inventory rendering.
    :rtype: dict
    """
    return {
        "inventory": await inventory_api.get("/"),
        "source_enum": SourceEnum,
        "sync_is_running": await SyncItemManager.sync_is_running(
            session,
            SyncInventoryEntityTypeEnum.INVENTORY,
        ),
        "can_sync": any(syncer.can_sync_inventory() for syncer in syncers),
    }


NodesContextDep = Annotated[dict, Depends(get_node_list_data)]


class NodeDetailContextResponse(BaseModel):
    """Node detail context response model.

    :param node: Node instance with its details.
    :type node: CreatedNode
    :param sync_is_running: Flag indicating if sync is in progress.
    :type sync_is_running: bool
    :param can_sync: Flag indicating if node can be synced.
    :type can_sync: bool
    """

    node: CreatedNode
    sync_is_running: bool
    can_sync: bool


class ServiceDetailContextResponse(BaseModel):
    """Service detail context response model.

    :param service: Service instance with its details.
    :type service: CreatedService
    :param sync_is_running: Flag indicating if sync is in progress.
    :type sync_is_running: bool
    :param can_sync: Flag indicating if service can be synced.
    :type can_sync: bool
    """

    service: CreatedService
    sync_is_running: bool
    can_sync: bool


class SchemaDetailContextResponse(BaseModel):
    """Schema detail context response model.

    :param schema: Schema instance with its details.
    :type schema: CreatedSchema
    :param sync_is_running: Flag indicating if sync is in progress.
    :type sync_is_running: bool
    :param can_sync: Flag indicating if schema can be synced.
    :type can_sync: bool
    """

    schema: CreatedSchema
    sync_is_running: bool
    can_sync: bool


async def get_node_detail_data(
    session: SessionDep,
    syncers: SyncersDep,
    node: CreatedNodeDep,
) -> dict:
    """Assemble and return node detail metadata for rendering or API response.

    :param session: Database session dependency.
    :type session: SessionDep
    :param syncers: List of initialized BaseSyncer instances.
    :type syncers: SyncersDep
    :param node: Node instance to get details for.
    :type node: CreatedNodeDep
    :return: A dictionary of context data used for node detail rendering.
    :rtype: dict
    """
    return {
        "node": node,
        "sync_is_running": await SyncItemManager.sync_is_running(
            session,
            SyncInventoryEntityTypeEnum.NODE,
        ),
        "can_sync": any(syncer.can_sync_node(node) for syncer in syncers),
    }


NodeDetailContextDep = Annotated[dict, Depends(get_node_detail_data)]


async def get_service_detail_data(
    session: SessionDep,
    syncers: SyncersDep,
    service: CreatedServiceDep,
) -> dict:
    """Assemble and return service detail metadata for rendering or API response.

    :param session: Database session dependency.
    :type session: SessionDep
    :param syncers: List of initialized BaseSyncer instances.
    :type syncers: SyncersDep
    :param service: Service instance to get details for.
    :type service: CreatedServiceDep
    :return: A dictionary of context data used for service detail rendering.
    :rtype: dict
    """
    return {
        "service": service,
        "sync_is_running": await SyncItemManager.sync_is_running(
            session,
            SyncInventoryEntityTypeEnum.SERVICE,
        ),
        "can_sync": any(syncer.can_sync_service(service) for syncer in syncers),
    }


ServiceDetailContextDep = Annotated[dict, Depends(get_service_detail_data)]


async def get_schema_detail_data(
    session: SessionDep,
    syncers: SyncersDep,
    schema: CreatedSchemaDep,
) -> dict:
    """Assemble and return schema detail metadata for rendering or API response.

    :param session: Database session dependency.
    :type session: SessionDep
    :param syncers: List of initialized BaseSyncer instances.
    :type syncers: SyncersDep
    :param schema: Schema instance to get details for.
    :type schema: CreatedSchemaDep
    :return: A dictionary of context data used for schema detail rendering.
    :rtype: dict
    """
    return {
        "schema": schema,
        "sync_is_running": await SyncItemManager.sync_is_running(
            session,
            SyncInventoryEntityTypeEnum.SCHEMA,
        ),
        "can_sync": any(syncer.can_sync_schema(schema) for syncer in syncers),
    }


SchemaDetailContextDep = Annotated[dict, Depends(get_schema_detail_data)]

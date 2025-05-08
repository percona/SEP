"""Define dependencies for the Inventory plugin."""

from typing import Annotated

from fastapi import Depends

from app.core.utils import import_var
from app.inventory.models import SourceEnum
from app.sep.config import sep_settings
from app.sep.crud import SyncItemManager
from app.sep.deps import InventoryAPI, SessionDep, TaskAPI
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


NodesDep = Annotated[dict, Depends(get_node_list_data)]

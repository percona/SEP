"""Define dependencies for the Inventory plugin."""

from typing import Annotated

from fastapi import Depends

from app.core.utils import import_var
from app.sep.config import sep_settings
from app.sep.deps import InventoryAPI, TaskAPI
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

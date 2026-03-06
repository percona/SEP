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

"""Define dependencies for the Inventory plugin."""

from typing import Annotated

from fastapi import Depends

from app.core.config import settings
from app.core.utils import import_var
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.sep.deps import InventoryClient, TasksClient
from app.sep.sync.models import BaseSyncer
from app.tasks.config import tasks_settings


def get_syncers(
    inventory_api: InventoryClient, tasks_api: TasksClient
) -> list[BaseSyncer]:
    """Initialize and return a list of BaseSyncer instances based on configuration.

    Import and initialize syncer classes as specified in the SEP settings, providing
    the necessary API clients and configuration parameters.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryClient
    :param tasks_api: The API client used to interact with the task service.
    :type tasks_api: TasksClient
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


async def get_syncers_standalone() -> list[BaseSyncer]:
    """Initialize syncer instances with API clients constructed from settings.

    Construct `RemoteAPI` clients for the inventory and tasks services from
    application settings, then build syncers the same way the request-context
    dependency does. Used by scheduled tasks that run outside of request
    context.

    :return: A list of initialized `BaseSyncer` instances.
    :rtype: list[BaseSyncer]
    """
    inventory_api = await settings.get_remote_api(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
        logger_name="inventory_api",
    )
    tasks_api = await settings.get_remote_api(
        endpoint=sep_settings.TASKS_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
        logger_name="tasks_api",
    )
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

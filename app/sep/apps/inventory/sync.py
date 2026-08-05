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

"""Provide synchronization functions for the SEP inventory."""

from app.core.security import get_internal_token
from app.sep.apps.inventory.deps import (
    filter_syncers_by_name,
    get_syncers_standalone,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.sync.models import BaseSyncer


async def run_scheduled_inventory_sync(syncer: str | None = None) -> None:
    """Execute scheduled inventory sync using configured internal token and syncers.

    Read the internal token from ``settings.SEP_INTERNAL_TOKEN`` and construct
    syncers from application settings. When ``syncer`` is set, only that syncer
    runs; when ``None`` or empty, every configured syncer runs.

    Designed for the CeleryExecutor: the executor forwards
    ``execution_request.meta`` from the periodic-task row as ``**kwargs``, so a
    row whose meta is ``{"syncer": "<qualified>"}`` resolves to the targeted
    single-syncer path while a row with empty meta resolves to the sync-all
    path.

    :param syncer: Fully qualified syncer name (e.g.
        ``"app.sep.sync.syncers.pmm.PMMSyncer"``), or ``None`` / empty for the
        sync-all path.
    :type syncer: str | None
    :raises ValueError: If ``SEP_INTERNAL_TOKEN`` is not configured, or if
        ``syncer`` is set but does not match any configured syncer that can
        sync inventory.
    """
    if (api_key := get_internal_token()) is None:
        raise ValueError(
            "SEP_INTERNAL_TOKEN must be configured for scheduled inventory "
            "sync. Set it in .env to a long random secret "
            "(e.g. `openssl rand -hex 32`)."
        )
    syncers = await get_syncers_standalone()
    selected = filter_syncers_by_name(
        syncers,
        syncer,
        lambda candidate: candidate.can_sync_inventory(),
    )
    await run_inventory_sync(api_key, *selected)


async def run_inventory_sync(api_key: str, *syncers: BaseSyncer) -> None:
    """Execute inventory synchronization using the provided syncers.

    Iterates over each ``BaseSyncer`` instance and invokes the ``sync_inventory`` method
    to perform inventory synchronization tasks asynchronously.

    :param syncers: One or more instances of ``BaseSyncer`` to perform inventory
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer in syncers:
        async with syncer.api_auth(api_key) as sync:
            await sync.sync_inventory()


async def run_node_sync(
    created_node: CreatedNode,
    api_key: str,
    *syncers: BaseSyncer,
) -> None:
    """Execute node synchronization for a created node using the provided syncers.

    Iterates over each ``BaseSyncer`` instance and invokes the ``sync_node`` method
    with the specified ``CreatedNode`` to perform node synchronization tasks
    asynchronously.

    :param created_node: The node that has been created and needs to be synchronized.
    :type created_node: CreatedNode
    :param syncers: One or more instances of ``BaseSyncer`` to perform node
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer.api_auth(api_key) as sync:
            await sync.sync_node(created_node, refresh_at_start=bool(syncer_index))


async def run_service_sync(
    created_service: CreatedService,
    api_key: str,
    *syncers: BaseSyncer,
) -> None:
    """Execute service synchronization for a created service using the provided syncers.

    Iterates over each ``BaseSyncer`` instance and invokes the ``sync_service`` method
    with the specified ``CreatedService`` to perform service synchronization tasks
    asynchronously.

    :param created_service: The service that has been created and needs to be
        synchronized.
    :type created_service: CreatedService
    :param syncers: One or more instances of ``BaseSyncer`` to perform service
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer.api_auth(api_key) as sync:
            await sync.sync_service(
                created_service,
                refresh_at_start=bool(syncer_index),
            )


async def run_schema_sync(
    created_schema: CreatedSchema,
    api_key: str,
    *syncers: BaseSyncer,
) -> None:
    """Execute schema synchronization for a created schema using the provided syncers.

    Iterates over each ``BaseSyncer`` instance and invokes the ``sync_schema`` method
    with the specified ``CreatedSchema`` to perform schema synchronization tasks
    asynchronously.

    :param created_schema: The schema that has been created and needs to be
        synchronized.
    :type created_schema: CreatedSchema
    :param syncers: One or more instances of ``BaseSyncer`` to perform schema
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer.api_auth(api_key) as sync:
            await sync.sync_schema(created_schema, refresh_at_start=bool(syncer_index))


async def run_table_sync(
    created_table: CreatedTable,
    api_key: str,
    *syncers: BaseSyncer,
) -> None:
    """Execute table synchronization for a created table using the provided syncers.

    Iterates over each ``BaseSyncer`` instance and invokes the ``sync_table`` method
    with the specified ``CreatedTable`` to perform table synchronization tasks
    asynchronously.

    :param created_table: The table that has been created and needs to be synchronized.
    :type created_table: CreatedTable
    :param syncers: One or more instances of ``BaseSyncer`` to perform table
        synchronization.
    :type syncers: BaseSyncer
    """
    for syncer_index, syncer in enumerate(syncers):
        async with syncer.api_auth(api_key) as sync:
            await sync.sync_table(created_table, refresh_at_start=bool(syncer_index))

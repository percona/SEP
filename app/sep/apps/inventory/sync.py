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

import logging
from collections.abc import Sequence

from kombu.exceptions import KombuError

from app.celery import celery
from app.core.security import get_internal_token
from app.sep.apps.inventory.deps import (
    filter_syncers_by_name,
    get_syncers_standalone,
)
from app.sep.crud import SyncInstanceManager, SyncItemManager
from app.sep.db import get_async_session_maker
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.sync.models import BaseSyncer
from app.tasks.models import (
    EXECUTE_TASK_BY_NAME_TASK,
    INVENTORY_SYNC_AFTER_KEY,
    INVENTORY_SYNC_TASK_NAME,
)

logger = logging.getLogger(__name__)


async def run_scheduled_inventory_sync(
    syncer: str | None = None,
    after_syncer: str | None = None,
    follower_syncers: Sequence[str] = (),
) -> str | None:
    """Execute scheduled inventory sync using configured internal token and syncers.

    Read the internal token from ``settings.SEP_INTERNAL_TOKEN`` and construct
    syncers from application settings. When ``syncer`` is set, only that syncer
    runs; when ``None`` or empty, every configured syncer runs.

    Designed for the CeleryExecutor: the executor forwards
    ``execution_request.meta`` from the periodic-task row as ``**kwargs``, so a
    row whose meta is ``{"syncer": "<qualified>"}`` resolves to the targeted
    single-syncer path while a row with empty meta resolves to the sync-all
    path.

    The tasks seeder orders a per-syncer schedule's first run after the pinned
    default's first completed sync through two meta keys, forwarded here as
    keyword arguments: a follower's run is skipped while ``after_syncer`` has
    never completed a whole-inventory pass, and the default's run then starts
    each follower that has never run. A skipped run returns a note saying so,
    which the executor writes to that run's log, so a run that synced nothing
    does not read as one that synced.

    :param syncer: Fully qualified syncer name (e.g.
        ``"app.sep.sync.syncers.pmm.PMMSyncer"``), or ``None`` / empty for the
        sync-all path.
    :param after_syncer: The pinned syncer this schedule waits on, or ``None`` to
        run unconditionally.
    :param follower_syncers: The per-syncer schedules to start once after this
        run, each only if it has never run. Defaults to none.
    :return: The note naming the syncer the run waits on when it was skipped,
        otherwise ``None``.
    :raises ValueError: If ``SEP_INTERNAL_TOKEN`` is not configured, or if a run
        that is not skipped names a ``syncer`` that matches no configured syncer
        able to sync inventory.
    :raises sqlalchemy.exc.SQLAlchemyError: When the SEP database cannot be read
        to decide the ordering.
    """
    if (api_key := get_internal_token()) is None:
        raise ValueError(
            "SEP_INTERNAL_TOKEN must be configured for scheduled inventory "
            "sync. Set it in .env to a long random secret "
            "(e.g. `openssl rand -hex 32`)."
        )
    if after_syncer and not await _inventory_sync_completed(after_syncer):
        deferral = (
            f"Skipped {syncer}: it waits until {after_syncer} completes its first "
            "inventory sync."
        )
        logger.info("%s", deferral)
        return deferral
    syncers = await get_syncers_standalone()
    selected = filter_syncers_by_name(
        syncers,
        syncer,
        lambda candidate: candidate.can_sync_inventory(),
    )
    await run_inventory_sync(api_key, *selected)
    if syncer and follower_syncers:
        await start_follower_first_runs(syncer, follower_syncers, syncers)
    return None


async def _inventory_sync_completed(syncer: str) -> bool:
    """Return whether ``syncer`` has ever completed a whole-inventory pass.

    :param syncer: The fully qualified syncer name.
    :return: Whether such a pass is recorded.
    :raises sqlalchemy.exc.SQLAlchemyError: When the SEP database cannot be read.
    """
    async with get_async_session_maker()() as session:
        return await SyncItemManager.inventory_sync_completed(session, syncer)


async def start_follower_first_runs(
    leader: str, followers: Sequence[str], syncers: list[BaseSyncer]
) -> None:
    """Start once each follower of ``leader`` that has never run.

    Nothing starts until ``leader`` has completed a whole-inventory pass, so a
    follower's first run reads the inventory that pass produced. A follower with
    any recorded run is left to its own schedule, and once every follower has one
    the leader's pass is no longer looked up. The start carries the same task and
    meta as a seeded follower's beat row, so the identical-task guard refuses it
    while that row's own fire is in flight. An enqueue failure is logged rather
    than raised: the follower's next beat fire runs it instead.

    :param leader: The fully qualified name of the syncer the followers wait on.
    :param followers: The fully qualified names of the followers to consider.
    :param syncers: The configured syncers, which a follower must resolve against.
    :raises sqlalchemy.exc.SQLAlchemyError: When the SEP database cannot be read.
    """
    async with get_async_session_maker()() as session:
        never_run = [
            follower
            for follower in followers
            if await SyncInstanceManager.first(session, syncer=follower) is None
        ]
        if not never_run or not await SyncItemManager.inventory_sync_completed(
            session, leader
        ):
            return
    for follower in never_run:
        try:
            filter_syncers_by_name(
                syncers, follower, lambda candidate: candidate.can_sync_inventory()
            )
        except ValueError:
            logger.warning(
                "Not starting %s after %s: it is not a configured inventory syncer",
                follower,
                leader,
            )
            continue
        try:
            celery.send_task(
                EXECUTE_TASK_BY_NAME_TASK,
                kwargs={
                    "task_name": INVENTORY_SYNC_TASK_NAME,
                    "execution_data": {
                        "meta": {"syncer": follower, INVENTORY_SYNC_AFTER_KEY: leader}
                    },
                },
            )
        except (OSError, KombuError):
            logger.exception(
                "Could not start %s after %s's first inventory sync", follower, leader
            )


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

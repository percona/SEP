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

"""Define database operations for SEP."""

import logging
from collections.abc import Collection
from datetime import timedelta
from typing import Any

from pydantic import UUID4
from sqlalchemy import func
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseSQLModelManager
from app.core.exceptions import HTTPConflictException
from app.core.utils.date_time import utc_now
from app.sep.models import (
    AppLifecycleEnum,
    AppRunningTask,
    AppState,
    SEPPluginPeriodicTask,
    SyncEntityAbsence,
    SyncEntityAbsenceWrite,
    SyncInstance,
    SyncInstanceWrite,
    SyncInventoryEntityTypeEnum,
    SyncItem,
    SyncItemWrite,
    SyncStatusEnum,
)
from app.sep.sync.exceptions import (
    SyncInstanceAlreadyInProgressError,
    SyncItemAlreadyInProgressError,
)

logger = logging.getLogger(__name__)


class SyncItemManager(BaseSQLModelManager):
    """Manage SyncItem operations, including creation, retrieval, and synchronization.

    This manager handles operations related to `SyncItem` models, such as creating new
    synchronization items, retrieving existing ones, and updating their synchronization
    status.

    :ivar Model: The SQLModel class this manager is responsible for (`SyncItem`).
    :vartype Model: type[SyncItem]
    """

    Model = SyncItem

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: SyncItemWrite,
        **extra_fields: Any,
    ) -> SyncItem:
        """Create and save a new SyncItem in the database.

        This method checks if a synchronization item with the same `entity_id`,
        `entity_type`, and `sync_instance_id` is already in progress. If so, it
        raises a `SyncItemAlreadyInProgressError`. Otherwise, it creates and saves
        the new `SyncItem`.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to create the new SyncItem.
        :type instance_create: SyncItemWrite
        :param extra_fields: Additional fields to be set on the SyncItem.
        :type extra_fields: Any
        :return: The newly created and saved SyncItem.
        :rtype: SyncItem
        :raises SyncItemAlreadyInProgressError: If a SyncItem with the same `entity_id`,
            `entity_type`, and `sync_instance_id` is already in progress.
        """
        sync_in_progress = await cls.first(
            session,
            entity_id=instance_create.entity_id,
            entity_type=instance_create.entity_type,
            sync_instance_id=instance_create.sync_instance_id,
        )
        if (
            sync_in_progress
        ):  # TODO: timeout for deleting old syncs  # noqa: TD002, TD003
            raise SyncItemAlreadyInProgressError(sync_in_progress)
        return await super().create(session, instance_create, **extra_fields)

    @classmethod
    async def sync_is_running(
        cls,
        session: AsyncSession,
        entity_type: SyncInventoryEntityTypeEnum,
        entity_id: int | None = None,
    ) -> bool:
        """Check if a synchronization is currently running for a given entity.

        Determines whether there is an ongoing synchronization process for the specified
        `entity_type` and optionally `entity_id`. A synchronization is considered
        running if its status is either `PENDING` or `RUNNING`.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param entity_type: The type of the entity to check synchronization status for.
        :type entity_type: SyncInventoryEntityTypeEnum
        :param entity_id: The ID of the entity to check synchronization status for.
            Defaults to `None`.
        :type entity_id: int | None
        :return: `True` if a synchronization is running, otherwise `False`.
        :rtype: bool
        """
        sync_in_progress = await cls.first(
            session,
            col(SyncItem.status).in_([SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING]),
            entity_id=entity_id,
            entity_type=entity_type,
        )
        return sync_in_progress is not None

    @classmethod
    async def start_sync(cls, session: AsyncSession, instance: SyncItem) -> SyncItem:
        """Mark a SyncItem as running.

        This method updates the status of the given `SyncItem` to `RUNNING` and saves
        the changes to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The SyncItem instance to update.
        :type instance: SyncItem
        :return: The updated SyncItem with status set to `RUNNING`.
        :rtype: SyncItem
        """
        instance.status = SyncStatusEnum.RUNNING
        return await cls.save(session, instance)

    @classmethod
    async def finish_sync(
        cls,
        session: AsyncSession,
        instance: SyncItem,
        status: SyncStatusEnum = SyncStatusEnum.SUCCESS,
    ) -> SyncItem:
        """Mark a SyncItem as finished with a given status.

        This method updates the status of the given `SyncItem` to the specified status
        (defaulting to `SUCCESS`) and saves the changes to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The SyncItem instance to update.
        :type instance: SyncItem
        :param status: The final status of the synchronization process. Defaults to
            `SUCCESS`.
        :type status: SyncStatusEnum
        :return: The updated SyncItem with the new status.
        :rtype: SyncItem
        """
        instance.status = status
        return await cls.save(session, instance)

    @classmethod
    async def fail_sync(
        cls,
        session: AsyncSession,
        instance: SyncItem,
    ) -> SyncItem:
        """Mark a SyncItem as failed.

        This method updates the status of the given `SyncItem` to `FAILED` and saves
        the changes to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance: The SyncItem instance to update.
        :type instance: SyncItem
        :return: The updated SyncItem with status set to `FAILED`.
        :rtype: SyncItem
        """
        return await cls.finish_sync(session, instance, SyncStatusEnum.FAILED)


class SyncInstanceManager(BaseSQLModelManager):
    """Manage SyncInstance operations, including creation, retrieval, and validation.

    This manager handles operations related to `SyncInstance` models, such as creating
    new synchronization instances, retrieving existing ones, and ensuring that no
    duplicate synchronization processes are running concurrently.

    :ivar Model: The SQLModel class this manager is responsible for (`SyncInstance`).
    :vartype Model: type[SyncInstance]
    """

    Model = SyncInstance

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: SyncInstanceWrite,
        *,
        stale_after: timedelta | None = None,
        **extra_fields: Any,
    ) -> SyncInstance:
        """Create and save a new SyncInstance in the database.

        This method checks if a synchronization instance with the same `syncer` is
        already in progress (i.e., has items with status `PENDING` or `RUNNING`). If so,
        it raises a `SyncInstanceAlreadyInProgressError`. Otherwise, it creates and
        saves the new `SyncInstance`.

        When ``stale_after`` is supplied, an in-progress conflict is first re-examined
        for abandoned runs: items left behind by a killed worker would otherwise
        block the syncer permanently, because the hanging-item sweep runs only when
        the run exits through its context manager.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param instance_create: The data used to create the new SyncInstance.
        :param stale_after: The age beyond which an idle in-progress run is presumed
            abandoned and reclaimed. Defaults to ``None``, which never reclaims.
        :param extra_fields: Additional fields to be set on the SyncInstance.
        :return: The newly created and saved SyncInstance.
        :raises SyncInstanceAlreadyInProgressError: If a SyncInstance with the same
            ``syncer`` is already in progress and could not be reclaimed as stale.
        """
        syncs_in_progress = await cls._items_in_progress(
            session, instance_create.syncer
        )
        if syncs_in_progress and stale_after is not None:
            await cls.reclaim_stale_runs(session, instance_create.syncer, stale_after)
            syncs_in_progress = await cls._items_in_progress(
                session,
                instance_create.syncer,
            )
        if syncs_in_progress:
            raise SyncInstanceAlreadyInProgressError(syncs_in_progress)
        return await super().create(session, instance_create, **extra_fields)

    @classmethod
    async def _items_in_progress(
        cls,
        session: AsyncSession,
        syncer: str,
    ) -> list[SyncItem]:
        """Return the non-terminal SyncItems belonging to a syncer's runs.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param syncer: The name of the synchronizer to inspect.
        :return: The ``PENDING`` or ``RUNNING`` items across that syncer's instances.
        """
        query = select(SyncItem).join(SyncInstance)
        query = cls._filter_query(
            query,
            col(SyncInstance.syncer) == syncer,
            col(SyncItem.status).in_([SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING]),
        )
        result = await cls._exec(session, query)
        return list(result.all())

    @classmethod
    async def reclaim_stale_runs(
        cls,
        session: AsyncSession,
        syncer: str,
        stale_after: timedelta,
        # pagination-ok: one syncer's abandoned runs. A run refuses to start while
        # another is in progress, so at most one leaks per worker death and every
        # reclaim clears the whole backlog.
    ) -> list[UUID4]:
        """Fail the runs of a syncer whose items stopped progressing long ago.

        A run is stale when the newest activity across **all** of its items predates
        ``stale_after``, so a run still making progress is never reclaimed. The item
        flip is a single conditional statement, so a second reclaimer arriving
        concurrently matches no rows rather than reclaiming twice. It covers every
        stale run already fenced as ``FAILED``, not only the ones this call fenced,
        so a reclaim interrupted between its two statements resumes on the next
        attempt instead of leaving the syncer blocked.

        ``snapshot_complete`` is deliberately left untouched: a partially applied run
        must never be counted as a complete generation.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param syncer: The name of the synchronizer whose runs should be inspected.
        :param stale_after: The age beyond which an idle run is presumed abandoned.
            Must exceed the longest expected runtime of a sync.
        :return: The IDs of the ``SyncInstance`` records this call actually reclaimed.
            A run that finished, or that a concurrent reclaimer already took, is not
            included.
        """
        in_progress = (
            select(col(SyncItem.sync_instance_id))
            .join(SyncInstance)
            .where(
                col(SyncInstance.syncer) == syncer,
                col(SyncItem.status).in_(
                    [SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING],
                ),
            )
        )
        last_activity = func.max(
            func.coalesce(col(SyncItem.updated_at), col(SyncItem.created_at)),
        )
        query = (
            select(col(SyncItem.sync_instance_id))
            .where(col(SyncItem.sync_instance_id).in_(in_progress))
            .group_by(col(SyncItem.sync_instance_id))
            .having(last_activity < utc_now() - stale_after)
        )
        result = await cls._exec(session, query)
        stale_instance_ids = list(result.all())
        if not stale_instance_ids:
            return []
        # The instance is fenced first, and only then are its items released.
        # Each statement commits on its own, so flipping the items first would
        # leave a window in which a reclaimed-but-live worker still reads
        # ``RUNNING`` and walks into its retire phase. The status predicate keeps
        # a run that finished between the query above and this update: it has
        # already written its own verdict, and is no longer anyone's to reclaim.
        reclaimed_ids = await cls.update_where(
            session,
            {"status": SyncStatusEnum.FAILED},
            col(SyncInstance.id).in_(stale_instance_ids),
            col(SyncInstance.status).in_(
                [SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING],
            ),
            returning=["id"],
        )
        # Items are released for every stale instance already fenced, not only the
        # ones this call fenced. A crash between the two statements leaves a FAILED
        # instance whose items were never released, and the update above then matches
        # nothing on every later attempt -- so without this the syncer would stay
        # blocked by exactly the abandoned run the reclaim exists to clear.
        fenced = await cls._exec(
            session,
            select(col(SyncInstance.id)).where(
                col(SyncInstance.id).in_(stale_instance_ids),
                col(SyncInstance.status) == SyncStatusEnum.FAILED,
            ),
        )
        fenced_ids = list(fenced.all())
        if not fenced_ids:
            return []
        if reclaimed_ids:
            logger.warning(
                "Reclaimed %d stale %s run(s): %s",
                len(reclaimed_ids),
                syncer,
                reclaimed_ids,
            )
        await SyncItemManager.update_where(
            session,
            {"status": SyncStatusEnum.FAILED},
            col(SyncItem.status).in_([SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING]),
            col(SyncItem.sync_instance_id).in_(fenced_ids),
        )
        return reclaimed_ids

    @classmethod
    async def is_still_owned(
        cls,
        session: AsyncSession,
        instance_id: UUID4,
    ) -> bool:
        """Check whether a run's SyncInstance has been reclaimed out from under it.

        The check a run performs before any destructive action, so it queries the
        ``status`` column directly rather than reading it off an ORM instance loaded
        earlier in the run, whose in-memory value would not reflect a reclaim
        committed by another worker.

        This establishes that *this* run was not reclaimed, not that it is the
        syncer's only run: the concurrent-run refusal in ``create`` reads and writes
        non-atomically, so two runs can each hold a ``RUNNING`` instance and both
        pass. Exclusivity needs an ownership primitive this does not provide.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param instance_id: The ID of the ``SyncInstance`` to check.
        :return: ``True`` while the instance is still ``RUNNING``, otherwise ``False``.
        """
        query = select(col(SyncInstance.status)).where(
            col(SyncInstance.id) == instance_id,
        )
        result = await cls._exec(session, query)
        return result.first() == SyncStatusEnum.RUNNING

    @classmethod
    async def finalize_run(
        cls,
        session: AsyncSession,
        instance_id: UUID4,
        *,
        failed: bool,
        snapshot_complete: bool | None,
    ) -> None:
        """Write the run-level verdict for a finishing SyncInstance.

        The transition is guarded on the instance still being ``RUNNING``, so a run
        that was reclaimed while it worked cannot overwrite the ``FAILED`` verdict
        (nor the ``NULL`` ``snapshot_complete``) the reclaim recorded.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param instance_id: The ID of the ``SyncInstance`` being finalized.
        :param failed: Whether an exception left the synchronization.
        :param snapshot_complete: Whether the run observed a complete generation, or
            ``None`` when the syncer does not produce one.
        """
        if not failed:
            failed = (
                await SyncItemManager.first(
                    session,
                    sync_instance_id=instance_id,
                    status=SyncStatusEnum.FAILED,
                )
                is not None
            )
        await cls.update_where(
            session,
            {
                "status": SyncStatusEnum.FAILED if failed else SyncStatusEnum.SUCCESS,
                "snapshot_complete": snapshot_complete,
            },
            col(SyncInstance.id) == instance_id,
            col(SyncInstance.status) == SyncStatusEnum.RUNNING,
        )

    @classmethod
    async def finish_hanging_items(
        cls,
        session: AsyncSession,
        instance_id: int,
    ) -> list[SyncItem]:
        """Mark all hanging SyncItems as failed for a given SyncInstance.

        This method retrieves all ``SyncItem`` instances associated with the given
        ``SyncInstance`` that are either ``PENDING`` or ``RUNNING`` and marks them as
        ``FAILED``. It then saves the updated ``SyncItem`` instances to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param instance_id: The ID of the ``SyncInstance`` whose hanging ``SyncItem``
            instances should be marked as failed.
        :return: A list of ``SyncItem`` instances that were marked as failed.
        """
        hanging_items = await SyncItemManager.list(
            session,
            col(SyncItem.status).in_([SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING]),
            sync_instance_id=instance_id,
        )
        for item in hanging_items:
            item.status = SyncStatusEnum.FAILED
        await SyncItemManager.save_batch(session, *hanging_items)
        return hanging_items


class SyncEntityAbsenceManager(BaseSQLModelManager):
    """Manage the missing-grace ledger backing deferred entity retirement.

    :ivar Model: The SQLModel class this manager is responsible for
        (``SyncEntityAbsence``).
    """

    Model = SyncEntityAbsence

    @classmethod
    async def record_missing(
        cls,
        session: AsyncSession,
        syncer: str,
        entity_type: SyncInventoryEntityTypeEnum,
        entity_id: int,
    ) -> int:
        """Count one more complete generation that did not include an entity.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param syncer: The name of the synchronizer that observed the absence.
        :param entity_type: The type of the absent inventory entity.
        :param entity_id: The local identifier of the absent inventory entity.
        :return: The number of consecutive complete generations reporting the entity
            absent, including this one.
        :raises HTTPBadRequestException: If the ledger insert hits a database error.
        """
        absence, _ = await cls.get_or_create(
            session,
            SyncEntityAbsenceWrite(
                syncer=syncer,
                entity_type=entity_type,
                entity_id=entity_id,
            ),
        )
        absence.missing_generations += 1
        await cls.save(session, absence)
        return absence.missing_generations

    @classmethod
    async def clear(
        cls,
        session: AsyncSession,
        syncer: str | None,
        entity_type: SyncInventoryEntityTypeEnum,
        *entity_ids: int,
    ) -> None:
        """Drop the ledger rows for entities that are present again.

        ``entity_id`` is only unique within an entity type and a syncer. A node and a
        service are numbered from separate sequences and collide freely, so the
        delete carries the full unique key rather than the IDs alone.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :param syncer: The name of the synchronizer that observed the entities, or
            ``None`` to drop the rows of every syncer. A row outlives the
            configuration that wrote it, so a caller clearing rows for an entity
            that is going away needs the syncer-agnostic form: rows left by a
            syncer since removed or renamed are unreachable by name.
        :param entity_type: The type of the inventory entities.
        :param entity_ids: The local identifiers whose ledger rows should be dropped.
        """
        if not entity_ids:
            return
        scope: dict[str, Any] = {"entity_type": entity_type}
        if syncer is not None:
            scope["syncer"] = syncer
        await cls.delete_where(
            session,
            col(SyncEntityAbsence.entity_id).in_(entity_ids),
            **scope,
        )


_ALLOWED_TRANSITIONS: dict[AppLifecycleEnum, frozenset[AppLifecycleEnum]] = {
    AppLifecycleEnum.ENABLED: frozenset({AppLifecycleEnum.DISABLING}),
    AppLifecycleEnum.DISABLED: frozenset({AppLifecycleEnum.ENABLING}),
    AppLifecycleEnum.DISABLING: frozenset({AppLifecycleEnum.DISABLED}),
    AppLifecycleEnum.ENABLING: frozenset({AppLifecycleEnum.ENABLED}),
}


class AppStateManager(BaseSQLModelManager):
    """Manage per-app runtime lifecycle state.

    :ivar Model: The SQLModel class this manager is responsible for (``AppState``).
    """

    Model = AppState

    @classmethod
    async def all_lifecycle_states(
        cls, session: AsyncSession
    ) -> dict[str, AppLifecycleEnum]:
        """Return a mapping of ``app_key`` to its lifecycle state for every row.

        :param session: The SQLAlchemy asynchronous session to use for the query.
        :return: A dictionary mapping each app key to its lifecycle state.
        """
        rows = await cls.values_list(session, ["app_key", "lifecycle_state"])
        return dict(rows)

    @classmethod
    async def current_lifecycle(
        cls, session: AsyncSession, app_key: str
    ) -> AppLifecycleEnum:
        """Return the current lifecycle state used by the toggle transition gate.

        A missing row reports ``ENABLED``: a configured plugin is active until an
        operator explicitly transitions it, mirroring :meth:`is_enabled`.

        :param session: The SQLAlchemy asynchronous session to use for the query.
        :param app_key: The app key to look up.
        :return: The persisted state, or ``ENABLED`` when no row exists.
        """
        row = await cls.first(session, app_key=app_key)
        return AppLifecycleEnum.ENABLED if row is None else row.lifecycle_state

    @classmethod
    async def is_enabled(cls, session: AsyncSession, app_key: str) -> bool:
        """Return whether the named app is currently ``ENABLED``.

        A missing row is treated as enabled: a configured plugin is active until
        an operator explicitly disables it. Any non-``ENABLED`` state (including
        the transitional ``ENABLING`` / ``DISABLING``) is not reachable.

        :param session: The SQLAlchemy asynchronous session to use for the query.
        :param app_key: The app key to look up.
        :return: ``True`` unless a non-``ENABLED`` row exists for the key.
        """
        row = await cls.first(session, app_key=app_key)
        return True if row is None else row.lifecycle_state == AppLifecycleEnum.ENABLED

    @classmethod
    async def should_cancel(cls, session: AsyncSession, app_key: str) -> bool:
        """Return whether a running task for ``app_key`` should cooperatively exit.

        ``True`` iff the app is mid- or post-disable (``DISABLING`` /
        ``DISABLED``) so a straggler that starts after ``DISABLED`` still
        self-cancels. A missing row reports ``ENABLED`` (-> ``False``), mirroring
        :meth:`is_enabled`. This is a pure predicate; the fail-soft on a transient
        DB error lives in :func:`app.sep.app_drain.should_cancel`, not here.

        :param session: The SQLAlchemy asynchronous session to use for the query.
        :param app_key: The app key to look up.
        :return: ``True`` when the app is ``DISABLING`` or ``DISABLED``.
        """
        row = await cls.first(session, app_key=app_key)
        return row is not None and row.lifecycle_state in {
            AppLifecycleEnum.DISABLING,
            AppLifecycleEnum.DISABLED,
        }

    @classmethod
    def assert_transition_allowed(
        cls, current: AppLifecycleEnum, target: AppLifecycleEnum
    ) -> None:
        """Assert that ``current`` -> ``target`` is a reachable lifecycle edge.

        The reachable edges are ``ENABLED`` -> ``DISABLING``, ``DISABLED`` ->
        ``ENABLING``, ``DISABLING`` -> ``DISABLED`` and ``ENABLING`` ->
        ``ENABLED``. Same-state, transitional-skipping, and any other move is
        rejected so idempotent retries do not silently appear to succeed.

        :param current: The app's current lifecycle state.
        :param target: The requested target lifecycle state.
        :raises HTTPConflictException: When the edge is not reachable (HTTP 409).
        """
        if target not in _ALLOWED_TRANSITIONS.get(current, frozenset()):
            raise HTTPConflictException(
                detail=f"Illegal app-state transition {current} -> {target}.",
            )


class AppRunningTaskManager(BaseSQLModelManager):
    """Manage in-flight SEP-app-owned Celery task rows.

    :ivar Model: The SQLModel class this manager is responsible for
        (``AppRunningTask``).
    """

    Model = AppRunningTask


class SEPPluginPeriodicTaskManager(BaseSQLModelManager):
    """Manage the plugin-owned periodic-task gating rows.

    :ivar Model: The SQLModel class this manager is responsible for
        (``SEPPluginPeriodicTask``).
    """

    Model = SEPPluginPeriodicTask

    @classmethod
    async def for_app_keys(
        cls, session: AsyncSession, app_keys: Collection[str] | None = None
    ) -> list[SEPPluginPeriodicTask]:
        """Return wrapper rows, optionally filtered to the given app keys.

        :param session: The SQLAlchemy asynchronous session to use for the query.
        :param app_keys: The app keys to restrict to, or ``None`` for every row.
        :return: The matching wrapper rows.
        """
        if app_keys is None:
            return await cls.list(session)
        return await cls.list(session, col(SEPPluginPeriodicTask.app_key).in_(app_keys))

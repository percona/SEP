"""Define database operations for SEP."""

from typing import Any

from sqlmodel import col
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseManager
from app.sep.models import SyncInstance
from app.sep.models import SyncInstanceWrite
from app.sep.models import SyncInventoryEntityTypeEnum
from app.sep.models import SyncItem
from app.sep.models import SyncItemWrite
from app.sep.models import SyncStatusEnum
from app.sep.sync.exceptions import SyncInstanceAlreadyInProgressError
from app.sep.sync.exceptions import SyncItemAlreadyInProgressError


class SyncItemManager(BaseManager):
    """Manage SyncItem operations, including creation, retrieval, and synchronization.

    This manager handles operations related to `SyncItem` models, such as creating new
    synchronization items, retrieving existing ones, and updating their synchronization
    status.

    :param Model: The SQLModel class this manager is responsible for (`SyncItem`).
    :type Model: type[SyncItem]
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
        if sync_in_progress:  # TODO: timeout for deleting old syncs
            raise SyncItemAlreadyInProgressError(sync_in_progress)
        return await super().create(session, instance_create, **extra_fields)

    @classmethod
    async def get_or_create(
        cls,
        session: AsyncSession,
        instance_create: SyncItemWrite,
        **extra_fields: Any,
    ) -> tuple[SyncItem, bool]:
        """Retrieve an existing SyncItem or create a new one if none exists.

        This method attempts to find a `SyncItem` with the specified `entity_id`,
        `entity_type`, and `sync_instance_id` that is either pending or running.
        If such an item exists, it returns it. Otherwise, it creates and saves a new
        `SyncItem`.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to create the new SyncItem if none exists.
        :type instance_create: SyncItemWrite
        :param extra_fields: Additional fields to be set on the SyncItem.
        :type extra_fields: Any
        :return: The existing or newly created SyncItem, and a bool specifying whether a
            new SyncItem was created.
        :rtype: tuple[SyncItem, bool]
        """
        sync_in_progress = await cls.first(
            session,
            status=SyncStatusEnum.PENDING,
            entity_id=instance_create.entity_id,
            entity_type=instance_create.entity_type,
            sync_instance_id=instance_create.sync_instance_id,
        )
        if sync_in_progress:
            return sync_in_progress, False
        return await super().create(session, instance_create, **extra_fields), True

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


class SyncInstanceManager(BaseManager):
    """Manage SyncInstance operations, including creation, retrieval, and validation.

    This manager handles operations related to `SyncInstance` models, such as creating
    new synchronization instances, retrieving existing ones, and ensuring that no
    duplicate synchronization processes are running concurrently.

    :param Model: The SQLModel class this manager is responsible for (`SyncInstance`).
    :type Model: type[SyncInstance]
    """

    Model = SyncInstance

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: SyncInstanceWrite,
        **extra_fields: Any,
    ) -> SyncInstance:
        """Create and save a new SyncInstance in the database.

        This method checks if a synchronization instance with the same `syncer` is
        already in progress (i.e., has items with status `PENDING` or `RUNNING`). If so,
        it raises a `SyncInstanceAlreadyInProgressError`. Otherwise, it creates and
        saves the new `SyncInstance`.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_create: The data used to create the new SyncInstance.
        :type instance_create: SyncInstanceWrite
        :param extra_fields: Additional fields to be set on the SyncInstance.
        :type extra_fields: Any
        :return: The newly created and saved SyncInstance.
        :rtype: SyncInstance
        :raises SyncInstanceAlreadyInProgressError: If a SyncInstance with the same
            `syncer` is already in progress.
        """
        query = select(SyncItem).join(SyncInstance)
        query = cls._filter_query(
            query,
            col(SyncInstance.syncer) == instance_create.syncer,
            col(SyncItem.status).in_([SyncStatusEnum.PENDING, SyncStatusEnum.RUNNING]),
        )
        result = await cls._exec(session, query)
        syncs_in_progress = list(result.all())
        if syncs_in_progress:
            raise SyncInstanceAlreadyInProgressError(syncs_in_progress)
        return await super().create(session, instance_create, **extra_fields)

    @classmethod
    async def finish_hanging_items(
        cls,
        session: AsyncSession,
        instance_id: int,
    ) -> list[SyncItem]:
        """Mark all hanging SyncItems as failed for a given SyncInstance.

        This method retrieves all `SyncItem` instances associated with the given
        `SyncInstance` that are either `PENDING` or `RUNNING` and marks them as
        `FAILED`. It then saves the updated `SyncItem` instances to the database.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param instance_id: The ID of the `SyncInstance` whose hanging `SyncItem`
            instances should be marked as failed.
        :type instance_id: int
        :return: A list of `SyncItem` instances that were marked as failed.
        :rtype: list[SyncItem]
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

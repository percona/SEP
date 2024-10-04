"""Define database operations for SEP."""

from typing import Any

from sqlmodel import col
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.db.crud import BaseManager
from app.sep.models import SyncInstance
from app.sep.models import SyncInstanceWrite
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


    Attributes
    ----------
    Model : type[SyncItem]
        The SQLModel class this manager is responsible for (`SyncItem`).

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

        This method checks if a synchronization item with the same `inventory_id`,
        `inventory_type`, and `sync_instance_id` is already in progress. If so, it
        raises a `SyncItemAlreadyInProgressError`. Otherwise, it creates and saves
        the new `SyncItem`.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance_create : SyncItemWrite
            The data used to create the new SyncItem.
        **extra_fields : Any
            Additional fields to be set on the SyncItem.

        Returns
        -------
        SyncItem
            The newly created and saved SyncItem.

        Raises
        ------
        SyncItemAlreadyInProgressError
            If a SyncItem with the same `inventory_id`, `inventory_type`, and
            `sync_instance_id` is already in progress.

        """
        sync_in_progress = await cls.first(
            session,
            inventory_id=instance_create.inventory_id,
            inventory_type=instance_create.inventory_type,
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

        This method attempts to find a `SyncItem` with the specified `inventory_id`,
        `inventory_type`, and `sync_instance_id` that is either pending or running.
        If such an item exists, it returns it. Otherwise, it creates and saves a new
        `SyncItem`.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance_create : SyncItemWrite
            The data used to create the new SyncItem if none exists.
        **extra_fields : Any
            Additional fields to be set on the SyncItem.

        Returns
        -------
        tuple[SyncItem, bool]
            The existing or newly created SyncItem, and a bool specifying whether a new
            SyncItem was created

        """
        sync_in_progress = await cls.first(
            session,
            status=SyncStatusEnum.PENDING,
            inventory_id=instance_create.inventory_id,
            inventory_type=instance_create.inventory_type,
            sync_instance_id=instance_create.sync_instance_id,
        )
        if sync_in_progress:
            return sync_in_progress, False
        return await super().create(session, instance_create, **extra_fields), True

    @classmethod
    async def start_sync(cls, session: AsyncSession, instance: SyncItem) -> SyncItem:
        """Mark a SyncItem as running.

        This method updates the status of the given `SyncItem` to `RUNNING` and saves
        the changes to the database.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance : SyncItem
            The SyncItem instance to update.

        Returns
        -------
        SyncItem
            The updated SyncItem with status set to `RUNNING`.

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

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance : SyncItem
            The SyncItem instance to update.
        status : SyncStatusEnum, optional
            The final status of the synchronization process. Defaults to `SUCCESS`.

        Returns
        -------
        SyncItem
            The updated SyncItem with the new status.

        """
        instance.status = status
        return await cls.save(session, instance)


class SyncInstanceManager(BaseManager):
    """Manage SyncInstance operations, including creation, retrieval, and validation.

    This manager handles operations related to `SyncInstance` models, such as creating
    new synchronization instances, retrieving existing ones, and ensuring that no
    duplicate synchronization processes are running concurrently.

    Attributes
    ----------
    Model : type[SyncInstance]
        The SQLModel class this manager is responsible for (`SyncInstance`).

    """

    Model = SyncInstance

    @classmethod
    async def create(
        cls,
        session: AsyncSession,
        instance_create: SyncInstanceWrite,
        **extra_fields: Any,
    ) -> SyncInstance:
        """Create and save a new SyncItem in the database.

        This method checks if a synchronization instance with the same `syncer` is
        already in progress (i.e., has items with status `PENDING` or `RUNNING`). If so,
        it raises a `SyncInstanceAlreadyInProgressError`. Otherwise, it creates and
        saves the new `SyncInstance`.

        Parameters
        ----------
        session : AsyncSession
            The SQLAlchemy asynchronous session to use for database operations.
        instance_create : SyncInstanceWrite
            The data used to create the new SyncItem.
        **extra_fields : Any
            Additional fields to be set on the SyncItem.

        Returns
        -------
        SyncInstance
            The newly created and saved SyncItem.

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

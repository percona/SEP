"""Define reusable Sync exceptions for the SEP app."""

from app.sep.models import SyncInventoryEntityTypeEnum, SyncItem


class SyncError(Exception):
    """Define a base synchronization error.

    This is the base class for all synchronization-related exceptions within the SEP
    application. It serves as a common ancestor for more specific synchronization error
    types.
    """


class SyncFailError(SyncError):
    """Raise when a synchronization process fails.

    This exception is triggered when an error occurs during the synchronization of a
    specific entity, resulting in the associated `SyncItem` being marked as failed.

    :param entity_type: The type of the entity that failed to synchronize.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param sync_item: The `SyncItem` instance that failed during synchronization.
    :type sync_item: SyncItem
    """

    def __init__(
        self,
        entity_type: SyncInventoryEntityTypeEnum,
        sync_item: SyncItem,
    ) -> None:
        self.entity_type = entity_type
        self.sync_item = sync_item
        message = f"Failed to sync {entity_type}: {sync_item}"
        super().__init__(message)


class SyncItemAlreadyInProgressError(SyncError):
    """Raise when a synchronization item is already in progress.

    This exception is triggered when an attempt is made to initiate a synchronization
    for an inventory item that is currently being synchronized.

    :param sync_in_progress: The synchronization item that is already in progress.
    :type sync_in_progress: SyncItem
    """

    def __init__(self, sync_in_progress: SyncItem) -> None:
        self.sync_in_progress = sync_in_progress
        message = (
            f"A sync item with this entity_id, entity_type, and "
            f"sync_instance is already in progress ({sync_in_progress})."
        )
        super().__init__(message)


class SyncInstanceAlreadyInProgressError(SyncError):
    """Raise when a synchronization instance is already in progress.

    This exception is raised when an attempt is made to start a synchronization process
    that is already being handled by another synchronizer.

    :param sync_items: The synchronization items that are already in progress.
    :type sync_items: Sequence[SyncItem]
    """

    def __init__(self, *sync_items: SyncItem) -> None:
        self.sync_items = sync_items
        message = (
            f"A sync instance with this syncer is already in progress for the "
            f"following sync items: {sync_items}."
        )
        super().__init__(message)

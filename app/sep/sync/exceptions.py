"""Define reusable Sync exceptions."""

from app.sep.models import SyncItem


class SyncError(Exception):
    """Define a base synchronization error.

    This is the base class for all synchronization-related exceptions within the SEP
    application. It serves as a common ancestor for more specific synchronization error
    types.
    """


class SyncItemAlreadyInProgressError(SyncError):
    """Raise when a synchronization item is already in progress.

    This exception is triggered when an attempt is made to initiate a synchronization
    for an inventory item that is currently being synchronized.

    Attributes
    ----------
    sync_in_progress : SyncItem
        The synchronization item that is already in progress.

    """

    def __init__(self, sync_in_progress: SyncItem) -> None:
        self.sync_in_progress = sync_in_progress
        message = (
            f"A sync item with this inventory_id, inventory_type, and "
            f"sync_instance is already in progress ({sync_in_progress})."
        )
        super().__init__(message)


class SyncInstanceAlreadyInProgressError(SyncError):
    """Raise when a synchronization instance is already in progress.

    This exception is raised when an attempt is made to start a synchronization process
    that is already being handled by another synchronizer.

    Attributes
    ----------
    *sync_items : SyncItem
        The synchronization items that are already in progress.

    """

    def __init__(self, *sync_items: SyncItem) -> None:
        self.sync_items = sync_items
        message = (
            f"A sync item with this syncer is already in progress for the "
            f"following sync items: {sync_items}."
        )
        super().__init__(message)

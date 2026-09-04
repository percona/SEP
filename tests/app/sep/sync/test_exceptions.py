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

"""Define tests for the app.sep.sync.exceptions module."""

from unittest.mock import MagicMock

from app.sep.sync.exceptions import (
    ExecutorHostNotFoundError,
    SyncError,
    SyncFailError,
    SyncInstanceAlreadyInProgressError,
    SyncItemAlreadyInProgressError,
)


class TestSyncFailError:
    """Test the SyncFailError exception."""

    def test_attributes_and_message(self):
        """Assert entity_type and sync_item are stored and message is formatted."""
        entity_type = MagicMock()
        entity_type.__str__ = MagicMock(return_value="schema")
        sync_item = MagicMock()
        sync_item.__str__ = MagicMock(return_value="item-42")

        exc = SyncFailError(entity_type, sync_item)

        assert exc.entity_type is entity_type
        assert exc.sync_item is sync_item
        assert str(exc) == "Failed to sync schema: item-42"

    def test_inherits_from_sync_error(self):
        """Assert SyncFailError is a subclass of SyncError."""
        assert issubclass(SyncFailError, SyncError)


class TestSyncItemAlreadyInProgressError:
    """Test the SyncItemAlreadyInProgressError exception."""

    def test_attribute_and_message(self):
        """Assert sync_in_progress is stored and message is formatted."""
        sync_in_progress = MagicMock()
        sync_in_progress.__str__ = MagicMock(return_value="sync-99")

        exc = SyncItemAlreadyInProgressError(sync_in_progress)

        assert exc.sync_in_progress is sync_in_progress
        assert str(exc) == (
            "A sync item with this entity_id, entity_type, and "
            "sync_instance is already in progress (sync-99)."
        )

    def test_inherits_from_sync_error(self):
        """Assert SyncItemAlreadyInProgressError is a subclass of SyncError."""
        assert issubclass(SyncItemAlreadyInProgressError, SyncError)


class TestSyncInstanceAlreadyInProgressError:
    """Test the SyncInstanceAlreadyInProgressError exception."""

    def test_single_item(self):
        """Assert single sync item is stored as a one-element tuple."""
        item = MagicMock()

        exc = SyncInstanceAlreadyInProgressError(item)

        assert exc.sync_items == (item,)
        assert str(exc).startswith(
            "A sync instance with this syncer is already in progress"
        )
        assert repr(item) in str(exc)

    def test_multiple_items(self):
        """Assert multiple sync items are stored as a tuple."""
        item_a = MagicMock()
        item_b = MagicMock()

        exc = SyncInstanceAlreadyInProgressError(item_a, item_b)

        assert exc.sync_items == (item_a, item_b)
        assert repr(item_a) in str(exc)
        assert repr(item_b) in str(exc)

    def test_detail_replaces_the_item_message(self):
        """Describe a conflict no item evidences without inventing an empty item list.

        A run-level conflict has no sync item to name, so the detail becomes the
        whole message and has to read as the conflict it is rather than as a run
        conflicting with an empty list.
        """
        exc = SyncInstanceAlreadyInProgressError(
            detail="A run of syncer 'pmm' is being created already.",
        )

        assert exc.sync_items == ()
        assert str(exc) == "A run of syncer 'pmm' is being created already."

    def test_inherits_from_sync_error(self):
        """Assert SyncInstanceAlreadyInProgressError is a subclass of SyncError."""
        assert issubclass(SyncInstanceAlreadyInProgressError, SyncError)


class TestExecutorHostNotFoundError:
    """Test the ``ExecutorHostNotFoundError`` exception."""

    def test_attributes_and_message(self):
        """Assert ``node_name``, ``node_address``, and ``available_hosts`` are stored and message is formatted."""
        exc = ExecutorHostNotFoundError(
            node_name="my-node",
            node_address="10.0.0.5",
            available_hosts={"executor-1": "10.0.0.1", "executor-2": "10.0.0.2"},
        )

        assert exc.node_name == "my-node"
        assert exc.node_address == "10.0.0.5"
        assert exc.available_hosts == {
            "executor-1": "10.0.0.1",
            "executor-2": "10.0.0.2",
        }
        assert str(exc) == (
            "No executor host matches node 'my-node' (address='10.0.0.5'). "
            "Available hosts: {'executor-1': '10.0.0.1', 'executor-2': '10.0.0.2'}"
        )

    def test_inherits_from_sync_error(self):
        """Assert ``ExecutorHostNotFoundError`` is a subclass of ``SyncError``."""
        assert issubclass(ExecutorHostNotFoundError, SyncError)

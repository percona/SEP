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

"""Define tests for the app.sep.crud module."""

from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import HTTPConflictException
from app.sep.crud import AppStateManager, SyncInstanceManager, SyncItemManager
from app.sep.models import (
    AppLifecycleEnum,
    AppState,
    SyncInstance,
    SyncInventoryEntityTypeEnum,
    SyncItem,
    SyncItemWrite,
    SyncStatusEnum,
)
from app.sep.sync.exceptions import (
    SyncInstanceAlreadyInProgressError,
    SyncItemAlreadyInProgressError,
)


def _build_sync_item(
    *,
    entity_id: int = 1,
    entity_type: SyncInventoryEntityTypeEnum = SyncInventoryEntityTypeEnum.NODE,
    status: SyncStatusEnum = SyncStatusEnum.PENDING,
    sync_instance_id: str | None = None,
) -> SyncItem:
    """Build a SyncItem instance for testing.

    :param entity_id: The entity ID.
    :type entity_id: int
    :param entity_type: The entity type.
    :type entity_type: SyncInventoryEntityTypeEnum
    :param status: The sync status.
    :type status: SyncStatusEnum
    :param sync_instance_id: The sync instance ID.
    :type sync_instance_id: str | None
    :return: A SyncItem instance.
    :rtype: SyncItem
    """
    return SyncItem(
        id=uuid4(),
        entity_id=entity_id,
        entity_type=entity_type,
        status=status,
        sync_instance_id=sync_instance_id or uuid4(),
    )


# ---------------------------------------------------------------------------
# SyncItemManager.create
# ---------------------------------------------------------------------------


class TestSyncItemManagerCreate:
    """Test SyncItemManager.create."""

    @pytest.mark.asyncio
    async def test_duplicate_raises(self) -> None:
        """Assert SyncItemAlreadyInProgressError is raised for a duplicate item."""
        session = AsyncMock()
        instance_id = uuid4()
        existing_item = _build_sync_item(sync_instance_id=instance_id)
        item_write = SyncItemWrite(
            entity_id=1,
            entity_type=SyncInventoryEntityTypeEnum.NODE,
            sync_instance_id=instance_id,
        )

        with patch.object(
            SyncItemManager, "first", return_value=existing_item
        ) as mock_first:
            with pytest.raises(SyncItemAlreadyInProgressError):
                await SyncItemManager.create(session, item_write)

            mock_first.assert_awaited_once_with(
                session,
                entity_id=item_write.entity_id,
                entity_type=item_write.entity_type,
                sync_instance_id=item_write.sync_instance_id,
            )

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """Assert a new SyncItem is created when no duplicate exists."""
        session = AsyncMock()
        instance_id = uuid4()
        item_write = SyncItemWrite(
            entity_id=2,
            entity_type=SyncInventoryEntityTypeEnum.SERVICE,
            sync_instance_id=instance_id,
        )
        expected_item = _build_sync_item(
            entity_id=2,
            entity_type=SyncInventoryEntityTypeEnum.SERVICE,
            sync_instance_id=instance_id,
        )

        with (
            patch.object(SyncItemManager, "first", return_value=None),
            patch(
                "app.sep.crud.BaseSQLModelManager.create", return_value=expected_item
            ) as mock_super_create,
        ):
            result = await SyncItemManager.create(session, item_write)

            assert result == expected_item
            mock_super_create.assert_awaited_once_with(session, item_write)


# ---------------------------------------------------------------------------
# SyncItemManager.get_or_create (overridden-create() guard, real session)
# ---------------------------------------------------------------------------


class TestSyncItemManagerGetOrCreate:
    """Test that get_or_create respects SyncItemManager's overridden create()."""

    @pytest.mark.asyncio
    async def test_respects_overridden_create_guard(self, session) -> None:
        """Assert the in-progress guard fires and no duplicate row is written.

        ``get_or_create``'s default existence filter includes ``status`` (PENDING),
        so it misses an already-``RUNNING`` item and falls into the create branch.
        That branch must route through ``SyncItemManager.create`` (not the
        conflict-tolerant fast path), whose guard raises
        ``SyncItemAlreadyInProgressError`` instead of silently inserting a second row.
        """
        instance = SyncInstance(syncer="test-syncer")
        session.add(instance)
        await session.commit()
        await session.refresh(instance)

        running_item = SyncItem(
            entity_id=1,
            entity_type=SyncInventoryEntityTypeEnum.NODE,
            status=SyncStatusEnum.RUNNING,
            sync_instance_id=instance.id,
        )
        session.add(running_item)
        await session.commit()

        item_write = SyncItemWrite(
            entity_id=1,
            entity_type=SyncInventoryEntityTypeEnum.NODE,
            sync_instance_id=instance.id,
        )

        with pytest.raises(SyncItemAlreadyInProgressError):
            await SyncItemManager.get_or_create(session, item_write)

        assert len(await SyncItemManager.list(session)) == 1


# ---------------------------------------------------------------------------
# SyncItemManager.sync_is_running
# ---------------------------------------------------------------------------


class TestSyncItemManagerSyncIsRunning:
    """Test SyncItemManager.sync_is_running."""

    @pytest.mark.asyncio
    async def test_returns_true_when_active(self) -> None:
        """Assert True is returned when a PENDING or RUNNING item exists."""
        session = AsyncMock()
        active_item = _build_sync_item(status=SyncStatusEnum.RUNNING)

        with patch.object(SyncItemManager, "first", return_value=active_item):
            result = await SyncItemManager.sync_is_running(
                session, SyncInventoryEntityTypeEnum.NODE, entity_id=1
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_no_active(self) -> None:
        """Assert False is returned when no active items exist."""
        session = AsyncMock()

        with patch.object(SyncItemManager, "first", return_value=None):
            result = await SyncItemManager.sync_is_running(
                session, SyncInventoryEntityTypeEnum.NODE, entity_id=1
            )

            assert result is False


# ---------------------------------------------------------------------------
# SyncItemManager.start_sync
# ---------------------------------------------------------------------------


class TestSyncItemManagerStartSync:
    """Test SyncItemManager.start_sync."""

    @pytest.mark.asyncio
    async def test_sets_status_to_running(self) -> None:
        """Assert the item's status is set to RUNNING and saved."""
        session = AsyncMock()
        item = _build_sync_item(status=SyncStatusEnum.PENDING)

        with patch.object(SyncItemManager, "save", return_value=item) as mock_save:
            result = await SyncItemManager.start_sync(session, item)

            assert item.status == SyncStatusEnum.RUNNING
            mock_save.assert_awaited_once_with(session, item)
            assert result == item


# ---------------------------------------------------------------------------
# SyncItemManager.finish_sync
# ---------------------------------------------------------------------------


class TestSyncItemManagerFinishSync:
    """Test SyncItemManager.finish_sync."""

    @pytest.mark.asyncio
    async def test_sets_given_status(self) -> None:
        """Assert the item's status is set to the given value and saved."""
        session = AsyncMock()
        item = _build_sync_item(status=SyncStatusEnum.RUNNING)

        with patch.object(SyncItemManager, "save", return_value=item) as mock_save:
            result = await SyncItemManager.finish_sync(
                session, item, SyncStatusEnum.SUCCESS
            )

            assert item.status == SyncStatusEnum.SUCCESS
            mock_save.assert_awaited_once_with(session, item)
            assert result == item

    @pytest.mark.asyncio
    async def test_defaults_to_success(self) -> None:
        """Assert the item's status defaults to SUCCESS when no status given."""
        session = AsyncMock()
        item = _build_sync_item(status=SyncStatusEnum.RUNNING)

        with patch.object(SyncItemManager, "save", return_value=item):
            await SyncItemManager.finish_sync(session, item)

            assert item.status == SyncStatusEnum.SUCCESS


# ---------------------------------------------------------------------------
# SyncItemManager.fail_sync
# ---------------------------------------------------------------------------


class TestSyncItemManagerFailSync:
    """Test SyncItemManager.fail_sync."""

    @pytest.mark.asyncio
    async def test_delegates_to_finish_sync_with_failed(self) -> None:
        """Assert fail_sync delegates to finish_sync with FAILED status."""
        session = AsyncMock()
        item = _build_sync_item(status=SyncStatusEnum.RUNNING)
        expected_item = _build_sync_item(status=SyncStatusEnum.FAILED)

        with patch.object(
            SyncItemManager, "finish_sync", return_value=expected_item
        ) as mock_finish:
            result = await SyncItemManager.fail_sync(session, item)

            mock_finish.assert_awaited_once_with(session, item, SyncStatusEnum.FAILED)
            assert result == expected_item


# ---------------------------------------------------------------------------
# SyncInstanceManager.create
# ---------------------------------------------------------------------------


class TestSyncInstanceManagerCreate:
    """Test SyncInstanceManager.create."""

    @pytest.mark.asyncio
    async def test_duplicate_raises(self) -> None:
        """Assert SyncInstanceAlreadyInProgressError for in-progress syncs."""
        session = AsyncMock()
        instance_write = MagicMock()
        instance_write.syncer = "test-syncer"

        active_items = [_build_sync_item(status=SyncStatusEnum.RUNNING)]
        mock_result = MagicMock()
        mock_result.all.return_value = active_items

        with (
            patch.object(SyncInstanceManager, "_exec", return_value=mock_result),
            pytest.raises(SyncInstanceAlreadyInProgressError),
        ):
            await SyncInstanceManager.create(session, instance_write)

    @pytest.mark.asyncio
    async def test_success(self) -> None:
        """Assert a new SyncInstance is created when no duplicates exist."""
        session = AsyncMock()
        instance_write = MagicMock()
        instance_write.syncer = "test-syncer"
        expected_instance = MagicMock(spec=SyncInstance)

        mock_result = MagicMock()
        mock_result.all.return_value = []

        with (
            patch.object(SyncInstanceManager, "_exec", return_value=mock_result),
            patch(
                "app.sep.crud.BaseSQLModelManager.create",
                return_value=expected_instance,
            ) as mock_super_create,
        ):
            result = await SyncInstanceManager.create(session, instance_write)

            assert result == expected_instance
            mock_super_create.assert_awaited_once()


# ---------------------------------------------------------------------------
# SyncInstanceManager.finish_hanging_items
# ---------------------------------------------------------------------------


class TestSyncInstanceManagerFinishHangingItems:
    """Test SyncInstanceManager.finish_hanging_items."""

    @pytest.mark.asyncio
    async def test_marks_active_items_as_failed(self) -> None:
        """Assert all PENDING/RUNNING items are marked FAILED."""
        session = AsyncMock()
        pending_item = _build_sync_item(status=SyncStatusEnum.PENDING)
        running_item = _build_sync_item(status=SyncStatusEnum.RUNNING)
        hanging_items = [pending_item, running_item]

        with (
            patch.object(
                SyncItemManager, "list", return_value=hanging_items
            ) as mock_list,
            patch.object(SyncItemManager, "save_batch") as mock_save_batch,
        ):
            result = await SyncInstanceManager.finish_hanging_items(session, 42)

            mock_list.assert_awaited_once()
            assert pending_item.status == SyncStatusEnum.FAILED
            assert running_item.status == SyncStatusEnum.FAILED
            mock_save_batch.assert_awaited_once_with(
                session, pending_item, running_item
            )
            assert result == hanging_items

    @pytest.mark.asyncio
    async def test_no_hanging_items(self) -> None:
        """Assert empty list is returned when no hanging items exist."""
        session = AsyncMock()

        with (
            patch.object(SyncItemManager, "list", return_value=[]),
            patch.object(SyncItemManager, "save_batch") as mock_save_batch,
        ):
            result = await SyncInstanceManager.finish_hanging_items(session, 99)

            mock_save_batch.assert_awaited_once_with(session)
            assert result == []


class TestAppStateManager:
    """Test suite for AppStateManager against a real session."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("state", list(AppLifecycleEnum))
    async def test_is_enabled_only_for_enabled_state(self, session, state) -> None:
        """``is_enabled`` is ``True`` only when the row's state is ``ENABLED``."""
        session.add(AppState(app_key="snippets", lifecycle_state=state))
        await session.commit()
        expected = state == AppLifecycleEnum.ENABLED
        assert await AppStateManager.is_enabled(session, "snippets") is expected

    @pytest.mark.asyncio
    async def test_is_enabled_true_for_missing_row(self, session) -> None:
        """A missing row is treated as enabled (active until explicitly disabled)."""
        assert await AppStateManager.is_enabled(session, "snippets") is True

    @pytest.mark.asyncio
    async def test_all_lifecycle_states_returns_mapping(self, session) -> None:
        """``all_lifecycle_states`` returns the ``app_key`` -> state mapping."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(
            AppState(app_key="checksums", lifecycle_state=AppLifecycleEnum.DISABLING)
        )
        await session.commit()
        assert await AppStateManager.all_lifecycle_states(session) == {
            "snippets": AppLifecycleEnum.ENABLED,
            "checksums": AppLifecycleEnum.DISABLING,
        }

    @pytest.mark.asyncio
    async def test_all_lifecycle_states_empty_table(self, session) -> None:
        """``all_lifecycle_states`` returns an empty mapping when no rows exist."""
        assert await AppStateManager.all_lifecycle_states(session) == {}

    @pytest.mark.asyncio
    async def test_all_lifecycle_states_returns_full_mapping(self, session) -> None:
        """``all_lifecycle_states`` returns the ``app_key`` -> state mapping."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(
            AppState(app_key="checksums", lifecycle_state=AppLifecycleEnum.DISABLING)
        )
        await session.commit()
        assert await AppStateManager.all_lifecycle_states(session) == {
            "snippets": AppLifecycleEnum.ENABLED,
            "checksums": AppLifecycleEnum.DISABLING,
        }

    @pytest.mark.asyncio
    async def test_current_lifecycle_reads_row_state(self, session) -> None:
        """``current_lifecycle`` returns the persisted state for an existing row."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLING)
        )
        await session.commit()
        current = await AppStateManager.current_lifecycle(session, "snippets")
        assert current is AppLifecycleEnum.DISABLING

    @pytest.mark.asyncio
    async def test_current_lifecycle_missing_row_is_enabled(self, session) -> None:
        """A missing row reports ``ENABLED`` for the transition gate."""
        current = await AppStateManager.current_lifecycle(session, "snippets")
        assert current is AppLifecycleEnum.ENABLED

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (AppLifecycleEnum.ENABLED, AppLifecycleEnum.DISABLING),
            (AppLifecycleEnum.DISABLED, AppLifecycleEnum.ENABLING),
            (AppLifecycleEnum.DISABLING, AppLifecycleEnum.DISABLED),
            (AppLifecycleEnum.ENABLING, AppLifecycleEnum.ENABLED),
        ],
    )
    def test_assert_transition_allowed_accepts_valid_edges(
        self, current, target
    ) -> None:
        """Each reachable edge passes the transition gate without raising."""
        AppStateManager.assert_transition_allowed(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (AppLifecycleEnum.ENABLED, AppLifecycleEnum.ENABLED),
            (AppLifecycleEnum.ENABLED, AppLifecycleEnum.DISABLED),
            (AppLifecycleEnum.DISABLED, AppLifecycleEnum.ENABLED),
            (AppLifecycleEnum.DISABLING, AppLifecycleEnum.ENABLED),
            (AppLifecycleEnum.DISABLING, AppLifecycleEnum.DISABLING),
            (AppLifecycleEnum.ENABLING, AppLifecycleEnum.DISABLED),
        ],
    )
    def test_assert_transition_allowed_rejects_illegal_edges(
        self, current, target
    ) -> None:
        """Every illegal edge raises ``HTTPConflictException`` (HTTP 409)."""
        with pytest.raises(HTTPConflictException):
            AppStateManager.assert_transition_allowed(current, target)

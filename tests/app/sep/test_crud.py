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

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.core.exceptions import HTTPConflictException
from app.core.utils.date_time import utc_now
from app.sep.crud import (
    AppStateManager,
    SyncEntityAbsenceManager,
    SyncInstanceManager,
    SyncItemManager,
)
from app.sep.models import (
    AppLifecycleEnum,
    AppState,
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

_NO_AGE = timedelta()


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


# ---------------------------------------------------------------------------
# SyncInstanceManager stale-run reclaim
# ---------------------------------------------------------------------------


async def _seed_run(
    session,
    *,
    syncer: str = "test-syncer",
    item_status: SyncStatusEnum = SyncStatusEnum.RUNNING,
    age: timedelta = _NO_AGE,
    instance_status: SyncStatusEnum = SyncStatusEnum.RUNNING,
) -> SyncInstance:
    """Persist a SyncInstance carrying one item aged ``age`` into the past."""
    instance = await SyncInstanceManager.save(
        session,
        SyncInstance(syncer=syncer, status=instance_status),
    )
    await SyncItemManager.save(
        session,
        SyncItem(
            entity_id=1,
            entity_type=SyncInventoryEntityTypeEnum.NODE,
            status=item_status,
            sync_instance_id=instance.id,
            created_at=utc_now() - age,
            updated_at=utc_now() - age,
        ),
    )
    return instance


class TestSyncInstanceManagerStaleReclaim:
    """Test the age-based stale-run reclaim on ``SyncInstanceManager.create``."""

    @pytest.mark.asyncio
    async def test_create_refuses_live_concurrent_run(self, session) -> None:
        """Refuse a run whose items are newer than ``stale_after``."""
        await _seed_run(session, age=timedelta(minutes=1))

        with pytest.raises(SyncInstanceAlreadyInProgressError):
            await SyncInstanceManager.create(
                session,
                SyncInstanceWrite(syncer="test-syncer"),
                stale_after=timedelta(hours=1),
            )

    @pytest.mark.asyncio
    async def test_create_does_not_reclaim_paused_live_run(self, session) -> None:
        """Refuse a run blocked mid-fetch whose items are untouched but recent."""
        await _seed_run(
            session, item_status=SyncStatusEnum.PENDING, age=timedelta(minutes=30)
        )

        with pytest.raises(SyncInstanceAlreadyInProgressError):
            await SyncInstanceManager.create(
                session,
                SyncInstanceWrite(syncer="test-syncer"),
                stale_after=timedelta(hours=1),
            )

    @pytest.mark.asyncio
    async def test_create_reclaims_stale_run_and_proceeds(self, session) -> None:
        """Mark a run failed when its newest activity predates ``stale_after``."""
        stale = await _seed_run(session, age=timedelta(hours=3))

        created = await SyncInstanceManager.create(
            session,
            SyncInstanceWrite(syncer="test-syncer"),
            stale_after=timedelta(hours=1),
        )

        assert created.id != stale.id
        items = await SyncItemManager.list(session, sync_instance_id=stale.id)
        assert [item.status for item in items] == [SyncStatusEnum.FAILED]
        reclaimed = await SyncInstanceManager.first(session, id=stale.id)
        assert reclaimed.status == SyncStatusEnum.FAILED

    @pytest.mark.asyncio
    async def test_reclaim_leaves_snapshot_complete_null(self, session) -> None:
        """Leave ``snapshot_complete`` unset so a reclaimed apply is incomplete."""
        stale = await _seed_run(session, age=timedelta(hours=3))

        await SyncInstanceManager.reclaim_stale_runs(
            session, "test-syncer", timedelta(hours=1)
        )

        reclaimed = await SyncInstanceManager.first(session, id=stale.id)
        assert reclaimed.snapshot_complete is None

    @pytest.mark.asyncio
    async def test_create_without_stale_after_never_reclaims(self, session) -> None:
        """Preserve the existing refusal behaviour when ``stale_after`` is unset."""
        await _seed_run(session, age=timedelta(days=7))

        with pytest.raises(SyncInstanceAlreadyInProgressError):
            await SyncInstanceManager.create(
                session, SyncInstanceWrite(syncer="test-syncer")
            )

    @pytest.mark.asyncio
    async def test_reclaim_is_idempotent_under_repeat(self, session) -> None:
        """Match no rows on a second reclaimer's conditional update."""
        stale = await _seed_run(session, age=timedelta(hours=3))

        first_pass = await SyncInstanceManager.reclaim_stale_runs(
            session, "test-syncer", timedelta(hours=1)
        )
        second_pass = await SyncInstanceManager.reclaim_stale_runs(
            session, "test-syncer", timedelta(hours=1)
        )

        assert first_pass == [stale.id]
        assert second_pass == []

    @pytest.mark.asyncio
    async def test_reclaim_fences_the_instance_before_releasing_items(
        self, session
    ) -> None:
        """Mark the run failed before the item flip commits.

        Each statement commits on its own, so releasing the items first would let
        a reclaimed-but-live worker still read ``RUNNING`` and retire entities.
        """
        instance = await _seed_run(session, age=timedelta(hours=3))
        owned_during_item_flip: list[bool] = []

        original = SyncItemManager.update_where

        async def _record_then_update(*args, **kwargs):
            owned_during_item_flip.append(
                await SyncInstanceManager.is_still_owned(session, instance.id)
            )
            return await original(*args, **kwargs)

        with patch.object(
            SyncItemManager, "update_where", side_effect=_record_then_update
        ):
            await SyncInstanceManager.reclaim_stale_runs(
                session, "test-syncer", timedelta(hours=1)
            )

        assert owned_during_item_flip == [False]

    @pytest.mark.asyncio
    async def test_reclaim_resumes_an_interrupted_release(self, session) -> None:
        """Release items of a stale run already fenced by an interrupted reclaim.

        The fence and the item release commit separately, so a crash between them
        leaves a ``FAILED`` instance whose items are still held. The conditional
        fence matches nothing on the retry, so only covering already-fenced runs
        keeps the syncer from staying blocked forever.
        """
        stale = await _seed_run(
            session,
            age=timedelta(hours=3),
            instance_status=SyncStatusEnum.FAILED,
        )

        reclaimed = await SyncInstanceManager.reclaim_stale_runs(
            session, "test-syncer", timedelta(hours=1)
        )

        assert reclaimed == []
        items = await SyncItemManager.list(session, sync_instance_id=stale.id)
        assert [item.status for item in items] == [SyncStatusEnum.FAILED]

    @pytest.mark.asyncio
    async def test_create_proceeds_after_an_interrupted_reclaim(self, session) -> None:
        """Let a new run start once an interrupted reclaim has been resumed."""
        await _seed_run(
            session,
            age=timedelta(hours=3),
            instance_status=SyncStatusEnum.FAILED,
        )

        created = await SyncInstanceManager.create(
            session,
            SyncInstanceWrite(syncer="test-syncer"),
            stale_after=timedelta(hours=1),
        )

        assert created.status == SyncStatusEnum.PENDING

    @pytest.mark.asyncio
    async def test_reclaim_ignores_other_syncers(self, session) -> None:
        """Leave a stale run belonging to another syncer untouched."""
        other = await _seed_run(session, syncer="other-syncer", age=timedelta(hours=3))

        reclaimed = await SyncInstanceManager.reclaim_stale_runs(
            session, "test-syncer", timedelta(hours=1)
        )

        assert reclaimed == []
        untouched = await SyncInstanceManager.first(session, id=other.id)
        assert untouched.status == SyncStatusEnum.RUNNING


# ---------------------------------------------------------------------------
# SyncInstanceManager.finalize_run / is_still_owned
# ---------------------------------------------------------------------------


class TestSyncInstanceManagerFinalizeRun:
    """Test the run-level status rollup written at ``__aexit__``."""

    @pytest.mark.asyncio
    async def test_finalize_run_success(self, session) -> None:
        """Roll an all-success run up to ``SUCCESS`` and record completeness."""
        instance = await _seed_run(session, item_status=SyncStatusEnum.SUCCESS)

        await SyncInstanceManager.finalize_run(
            session, instance.id, failed=False, snapshot_complete=True
        )

        finalized = await SyncInstanceManager.first(session, id=instance.id)
        assert finalized.status == SyncStatusEnum.SUCCESS
        assert finalized.snapshot_complete is True

    @pytest.mark.asyncio
    async def test_finalize_run_failed_item(self, session) -> None:
        """Roll the run up to ``FAILED`` when any item failed."""
        instance = await _seed_run(session, item_status=SyncStatusEnum.FAILED)

        await SyncInstanceManager.finalize_run(
            session, instance.id, failed=False, snapshot_complete=True
        )

        finalized = await SyncInstanceManager.first(session, id=instance.id)
        assert finalized.status == SyncStatusEnum.FAILED

    @pytest.mark.asyncio
    async def test_finalize_run_propagates_raised_exception(self, session) -> None:
        """``failed=True`` (an exception left ``__aexit__``) rolls up to ``FAILED``."""
        instance = await _seed_run(session, item_status=SyncStatusEnum.SUCCESS)

        await SyncInstanceManager.finalize_run(
            session, instance.id, failed=True, snapshot_complete=False
        )

        finalized = await SyncInstanceManager.first(session, id=instance.id)
        assert finalized.status == SyncStatusEnum.FAILED

    @pytest.mark.asyncio
    async def test_finalize_run_leaves_reclaimed_instance_alone(self, session) -> None:
        """Keep the ``FAILED`` verdict a falsely-reclaimed worker would overwrite."""
        instance = await _seed_run(
            session,
            item_status=SyncStatusEnum.SUCCESS,
            instance_status=SyncStatusEnum.FAILED,
        )

        await SyncInstanceManager.finalize_run(
            session, instance.id, failed=False, snapshot_complete=True
        )

        finalized = await SyncInstanceManager.first(session, id=instance.id)
        assert finalized.status == SyncStatusEnum.FAILED
        assert finalized.snapshot_complete is None

    @pytest.mark.asyncio
    async def test_is_still_owned_tracks_the_persisted_status(self, session) -> None:
        """Read the persisted row, not the caller's in-memory copy."""
        instance = await _seed_run(session, age=timedelta(hours=3))

        assert await SyncInstanceManager.is_still_owned(session, instance.id) is True

        await SyncInstanceManager.reclaim_stale_runs(
            session, "test-syncer", timedelta(hours=1)
        )

        assert await SyncInstanceManager.is_still_owned(session, instance.id) is False


# ---------------------------------------------------------------------------
# SyncEntityAbsenceManager
# ---------------------------------------------------------------------------


class TestSyncEntityAbsenceManager:
    """Test the missing-grace ledger."""

    @pytest.mark.asyncio
    async def test_record_missing_increments_and_clear_deletes(self, session) -> None:
        """Accumulate consecutive absences and drop the row on reappearance."""
        first = await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )
        second = await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )

        assert (first, second) == (1, 2)

        await SyncEntityAbsenceManager.clear(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )

        assert await SyncEntityAbsenceManager.list(session) == []

    @pytest.mark.asyncio
    async def test_clear_without_ids_is_a_noop(self, session) -> None:
        """Delete nothing when the id tuple is empty."""
        await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )

        await SyncEntityAbsenceManager.clear(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE
        )

        assert len(await SyncEntityAbsenceManager.list(session)) == 1

    @pytest.mark.asyncio
    async def test_clear_does_not_cross_entity_type_or_syncer(self, session) -> None:
        """``entity_id`` collides across types and syncers, so the key is all three."""
        await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )
        await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.SERVICE, 7
        )
        await SyncEntityAbsenceManager.record_missing(
            session, "mysql", SyncInventoryEntityTypeEnum.NODE, 7
        )

        await SyncEntityAbsenceManager.clear(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )

        survivors = {
            (row.syncer, row.entity_type)
            for row in await SyncEntityAbsenceManager.list(session)
        }
        assert survivors == {
            ("pmm", SyncInventoryEntityTypeEnum.SERVICE),
            ("mysql", SyncInventoryEntityTypeEnum.NODE),
        }

    @pytest.mark.asyncio
    async def test_a_null_syncer_clears_the_entity_across_every_syncer(
        self, session
    ) -> None:
        """Drop every syncer's row for an entity that is going away for good.

        A row outlives the configuration that wrote it, so a caller collecting
        the entity itself cannot enumerate the syncers that observed it.
        """
        await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.NODE, 7
        )
        await SyncEntityAbsenceManager.record_missing(
            session, "mysql", SyncInventoryEntityTypeEnum.NODE, 7
        )
        await SyncEntityAbsenceManager.record_missing(
            session, "pmm", SyncInventoryEntityTypeEnum.SERVICE, 7
        )

        await SyncEntityAbsenceManager.clear(
            session, None, SyncInventoryEntityTypeEnum.NODE, 7
        )

        survivors = {
            (row.syncer, row.entity_type)
            for row in await SyncEntityAbsenceManager.list(session)
        }
        assert survivors == {("pmm", SyncInventoryEntityTypeEnum.SERVICE)}

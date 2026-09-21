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

"""Define tests for the app.sep.apps.inventory.sync module."""

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from kombu.exceptions import KombuError
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.celery import celery
from app.core.config import settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.utils import json_serializer
from app.sep.apps.inventory.sync import (
    run_inventory_sync,
    run_node_sync,
    run_scheduled_inventory_sync,
    run_schema_sync,
    run_service_sync,
    run_table_sync,
    start_follower_first_runs,
)
from app.sep.crud import SyncInstanceManager, SyncItemManager
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.models import (
    SyncInstanceWrite,
    SyncInventoryEntityTypeEnum,
    SyncItemWrite,
    SyncStatusEnum,
)
from app.sep.sync.models import BaseSyncer
from app.tasks.models import (
    EXECUTE_TASK_BY_NAME_TASK,
    INVENTORY_SYNC_AFTER_KEY,
    INVENTORY_SYNC_TASK_NAME,
)
from tests.app.db_schema import apply_schema
from tests.app.factories import (
    CreatedNodeFactory,
    CreatedSchemaFactory,
    CreatedServiceFactory,
    CreatedTableFactory,
)


class _StubPMMSyncer:
    """Stand-in syncer used to exercise ``filter_syncers_by_name`` matching."""

    def can_sync_inventory(self) -> bool:
        return True


class _StubMySQLSyncer:
    """Second stand-in syncer used to exercise multi-syncer selection."""

    def can_sync_inventory(self) -> bool:
        return True


_PMM_STUB_NAME = f"{_StubPMMSyncer.__module__}.{_StubPMMSyncer.__name__}"
_MYSQL_STUB_NAME = f"{_StubMySQLSyncer.__module__}.{_StubMySQLSyncer.__name__}"


@pytest.fixture
def mock_base_syncer_factory():
    """Create a mock BaseSyncer whose api_auth is an async context manager."""

    def _create_mock_syncer():
        syncer = AsyncMock(spec=BaseSyncer)

        @asynccontextmanager
        async def api_auth(_api_key: str):
            yield syncer

        syncer.api_auth = api_auth
        return syncer

    return _create_mock_syncer


@pytest.fixture
def created_node() -> CreatedNode:
    """Return a fake created node."""
    return CreatedNodeFactory.build()


@pytest.fixture
def created_service(created_node) -> CreatedService:
    """Return a fake created service."""
    created_service = CreatedServiceFactory.build()
    created_service.node = created_node
    return created_service


@pytest.fixture
def created_schema(created_service) -> CreatedSchema:
    """Return a fake created Schema."""
    created_schema = CreatedSchemaFactory.build()
    created_schema.service = created_service
    return created_schema


@pytest.fixture
def created_table() -> CreatedTable:
    """Return a fake created Table."""
    return CreatedTableFactory.build()


@pytest.mark.asyncio
async def test_run_inventory_sync(mock_base_syncer_factory):
    """Test executing inventory synchronization using the provided syncers."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_inventory_sync("test-key", syncer1, syncer2)

    syncer1.sync_inventory.assert_awaited_once()
    syncer2.sync_inventory.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_node_sync(created_node, mock_base_syncer_factory):
    """Test executing node synchronization for a created node."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_node_sync(created_node, "test-key", syncer1, syncer2)

    syncer1.sync_node.assert_awaited_once_with(created_node, refresh_at_start=False)
    syncer2.sync_node.assert_awaited_once_with(created_node, refresh_at_start=True)


@pytest.mark.asyncio
async def test_run_service_sync(created_service, mock_base_syncer_factory):
    """Test executing service synchronization for a created service."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_service_sync(created_service, "test-key", syncer1, syncer2)

    syncer1.sync_service.assert_awaited_once_with(
        created_service, refresh_at_start=False
    )
    syncer2.sync_service.assert_awaited_once_with(
        created_service, refresh_at_start=True
    )


@pytest.mark.asyncio
async def test_run_schema_sync(created_schema, mock_base_syncer_factory):
    """Test executing schema synchronization for a created schema."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_schema_sync(created_schema, "test-key", syncer1, syncer2)

    syncer1.sync_schema.assert_awaited_once_with(created_schema, refresh_at_start=False)
    syncer2.sync_schema.assert_awaited_once_with(created_schema, refresh_at_start=True)


@pytest.mark.asyncio
async def test_run_table_sync(created_table, mock_base_syncer_factory):
    """Test executing table synchronization for a created table."""
    syncer1 = mock_base_syncer_factory()
    syncer2 = mock_base_syncer_factory()

    await run_table_sync(created_table, "test-key", syncer1, syncer2)

    syncer1.sync_table.assert_awaited_once_with(created_table, refresh_at_start=False)
    syncer2.sync_table.assert_awaited_once_with(created_table, refresh_at_start=True)


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync(mocker, mock_base_syncer_factory):
    """Assert run_scheduled_inventory_sync reads internal token and constructs syncers."""
    syncer = mock_base_syncer_factory()
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("test-api-key"))
    mocker.patch(
        "app.sep.apps.inventory.sync.get_syncers_standalone",
        return_value=[syncer],
    )
    mock_run = mocker.patch(
        "app.sep.apps.inventory.sync.run_inventory_sync",
        new=AsyncMock(),
    )
    await run_scheduled_inventory_sync()
    mock_run.assert_awaited_once_with("test-api-key", syncer)


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_no_token(mocker):
    """Assert run_scheduled_inventory_sync raises when SEP_INTERNAL_TOKEN unset."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", None)
    with pytest.raises(
        ValueError,
        match=r"SEP_INTERNAL_TOKEN must be configured.*openssl rand -hex 32",
    ):
        await run_scheduled_inventory_sync()


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_empty_token(mocker):
    """Assert run_scheduled_inventory_sync raises when SEP_INTERNAL_TOKEN is empty."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr(""))
    with pytest.raises(ValueError, match=r"SEP_INTERNAL_TOKEN must be configured"):
        await run_scheduled_inventory_sync()


def _patch_scheduled_sync_env(mocker, syncers):
    """Patch the internal token and syncer-construction hooks for scheduled-sync tests."""
    mocker.patch.object(settings, "SEP_INTERNAL_TOKEN", SecretStr("test-api-key"))
    mocker.patch(
        "app.sep.apps.inventory.sync.get_syncers_standalone",
        return_value=syncers,
    )
    return mocker.patch(
        "app.sep.apps.inventory.sync.run_inventory_sync",
        new=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_runs_all_when_syncer_none(mocker):
    """Sync-all path: every configured syncer is forwarded in declaration order."""
    syncers = [_StubPMMSyncer(), _StubMySQLSyncer()]
    mock_run = _patch_scheduled_sync_env(mocker, syncers)
    await run_scheduled_inventory_sync()
    mock_run.assert_awaited_once_with("test-api-key", *syncers)


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_runs_all_when_syncer_empty_string(mocker):
    """An empty syncer string is treated as the sync-all path."""
    syncers = [_StubPMMSyncer(), _StubMySQLSyncer()]
    mock_run = _patch_scheduled_sync_env(mocker, syncers)
    await run_scheduled_inventory_sync(syncer="")
    mock_run.assert_awaited_once_with("test-api-key", *syncers)


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_targets_named_syncer(mocker):
    """A matching qualified name resolves to a single-syncer call."""
    pmm = _StubPMMSyncer()
    mysql = _StubMySQLSyncer()
    mock_run = _patch_scheduled_sync_env(mocker, [pmm, mysql])
    await run_scheduled_inventory_sync(syncer=_MYSQL_STUB_NAME)
    mock_run.assert_awaited_once_with("test-api-key", mysql)


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_unknown_syncer_raises(mocker):
    """An unknown syncer raises ``ValueError`` without invoking the run."""
    mock_run = _patch_scheduled_sync_env(mocker, [_StubPMMSyncer()])
    with pytest.raises(ValueError, match=r"app\.fake\.UnknownSyncer"):
        await run_scheduled_inventory_sync(syncer="app.fake.UnknownSyncer")
    mock_run.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_scheduled_inventory_sync_incapable_syncer_raises(mocker):
    """A configured syncer that cannot sync inventory is rejected by name."""
    pmm = _StubPMMSyncer()
    mocker.patch.object(pmm, "can_sync_inventory", return_value=False)
    mock_run = _patch_scheduled_sync_env(mocker, [pmm])
    with pytest.raises(ValueError, match=re.escape(_PMM_STUB_NAME)):
        await run_scheduled_inventory_sync(syncer=_PMM_STUB_NAME)
    mock_run.assert_not_awaited()


class _NoopInventorySyncer(BaseSyncer):
    """Complete an inventory pass without reading any remote source."""

    SYNC_TO_LIMIT = SyncInventoryEntityTypeEnum.INVENTORY

    async def perform_inventory_sync(self) -> None:
        """Finish the pass at once, leaving the run lifecycle around it real."""


class _LeaderSyncer(_NoopInventorySyncer):
    """Stand in for the pinned default the per-syncer schedules follow."""


class _FollowerSyncer(_NoopInventorySyncer):
    """Stand in for a per-syncer schedule whose first run follows the default."""


_LEADER = _LeaderSyncer.get_name()
_FOLLOWER = _FollowerSyncer.get_name()


@pytest_asyncio.fixture(name="sep_maker")
async def sep_maker_fixture() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Provide a session maker bound to an in-memory SEP DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await apply_schema(conn, SQLModel.metadata)
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


def _route_sessions(mocker, maker: async_sessionmaker[AsyncSession]) -> None:
    """Point both the syncer lifecycle and the ordering gate at ``maker``.

    Each module binds ``get_async_session_maker`` itself, so patching one would
    leave the run writing one database while the gate reads another.
    """
    mocker.patch("app.sep.sync.models.get_async_session_maker", return_value=maker)
    mocker.patch(
        "app.sep.apps.inventory.sync.get_async_session_maker", return_value=maker
    )


async def _record_run(
    maker: async_sessionmaker[AsyncSession],
    syncer: str,
    inventory_status: SyncStatusEnum = SyncStatusEnum.SUCCESS,
) -> None:
    """Persist a finished run of ``syncer`` whose INVENTORY item ended as given."""
    async with maker() as session:
        instance = await SyncInstanceManager.create(
            session, SyncInstanceWrite(syncer=syncer, status=inventory_status)
        )
        await SyncItemManager.create(
            session,
            SyncItemWrite(
                entity_type=SyncInventoryEntityTypeEnum.INVENTORY,
                entity_id=None,
                sync_instance_id=instance.id,
                status=inventory_status,
            ),
        )


def _follower_kick(follower: str, leader: str) -> dict[str, object]:
    """Return the ``execute_task_by_name`` kwargs that start ``follower`` once."""
    return {
        "task_name": INVENTORY_SYNC_TASK_NAME,
        "execution_data": {
            "meta": {"syncer": follower, INVENTORY_SYNC_AFTER_KEY: leader}
        },
    }


@pytest.mark.asyncio
async def test_a_follower_defers_until_the_leader_completes(
    sep_maker, mocker, mock_remote_api
):
    """Skip the follower's run, opening no run at all, while the leader never finished.

    A deferred run must not leave a ``SyncInstance`` behind: the kick starts only
    followers with none, so a stray row would stop the follower ever being started.
    """
    _route_sessions(mocker, sep_maker)
    mocker.patch(
        "app.sep.apps.inventory.sync.get_syncers_standalone",
        return_value=[_FollowerSyncer(inventory_api=mock_remote_api)],
    )

    await run_scheduled_inventory_sync(syncer=_FOLLOWER, after_syncer=_LEADER)

    async with sep_maker() as session:
        assert await SyncInstanceManager.list(session) == []


@pytest.mark.asyncio
async def test_a_follower_runs_once_the_leader_completed(
    sep_maker, mocker, mock_remote_api
):
    """Run the follower's sync once the leader has finished a whole pass."""
    _route_sessions(mocker, sep_maker)
    await _record_run(sep_maker, _LEADER)
    mocker.patch(
        "app.sep.apps.inventory.sync.get_syncers_standalone",
        return_value=[_FollowerSyncer(inventory_api=mock_remote_api)],
    )

    await run_scheduled_inventory_sync(syncer=_FOLLOWER, after_syncer=_LEADER)

    async with sep_maker() as session:
        (run,) = await SyncInstanceManager.list(session, syncer=_FOLLOWER)
    assert run.status == SyncStatusEnum.SUCCESS


class TestStartFollowerFirstRuns:
    """Test the leader-side start of followers that have never run."""

    @pytest.fixture
    def send_task(self, mocker, sep_maker) -> MagicMock:
        """Route the gate at the in-memory DB and replace the broker call."""
        _route_sessions(mocker, sep_maker)
        return mocker.patch.object(celery, "send_task")

    @pytest.mark.asyncio
    async def test_starts_a_never_run_follower_once(self, sep_maker, send_task):
        """Start a configured follower with no run of its own, exactly once."""
        await _record_run(sep_maker, _PMM_STUB_NAME)

        await start_follower_first_runs(
            _PMM_STUB_NAME, [_MYSQL_STUB_NAME], [_StubPMMSyncer(), _StubMySQLSyncer()]
        )

        send_task.assert_called_once_with(
            EXECUTE_TASK_BY_NAME_TASK,
            kwargs=_follower_kick(_MYSQL_STUB_NAME, _PMM_STUB_NAME),
        )

    @pytest.mark.asyncio
    async def test_leaves_a_follower_that_already_ran(self, sep_maker, send_task):
        """Leave a follower alone once it has any run, even a failed one."""
        await _record_run(sep_maker, _PMM_STUB_NAME)
        await _record_run(sep_maker, _MYSQL_STUB_NAME, SyncStatusEnum.FAILED)

        await start_follower_first_runs(
            _PMM_STUB_NAME, [_MYSQL_STUB_NAME], [_StubPMMSyncer(), _StubMySQLSyncer()]
        )

        send_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_waits_for_a_completed_leader_pass(self, sep_maker, send_task):
        """Start nothing while the leader's only pass could not list the inventory."""
        await _record_run(sep_maker, _PMM_STUB_NAME, SyncStatusEnum.FAILED)

        await start_follower_first_runs(
            _PMM_STUB_NAME, [_MYSQL_STUB_NAME], [_StubPMMSyncer(), _StubMySQLSyncer()]
        )

        send_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_an_unconfigured_follower_with_a_warning(
        self, sep_maker, send_task, caplog
    ):
        """Skip a follower no configured syncer resolves, naming it in the log."""
        await _record_run(sep_maker, _PMM_STUB_NAME)

        with caplog.at_level(logging.WARNING, logger="app.sep.apps.inventory.sync"):
            await start_follower_first_runs(
                _PMM_STUB_NAME, [_MYSQL_STUB_NAME], [_StubPMMSyncer()]
            )

        send_task.assert_not_called()
        assert _MYSQL_STUB_NAME in caplog.text

    @pytest.mark.asyncio
    async def test_logs_rather_than_raises_when_the_broker_refuses(
        self, sep_maker, send_task, caplog
    ):
        """Log an enqueue failure and return, leaving the follower's own schedule."""
        await _record_run(sep_maker, _PMM_STUB_NAME)
        send_task.side_effect = KombuError("broker unreachable")

        with caplog.at_level(logging.ERROR, logger="app.sep.apps.inventory.sync"):
            await start_follower_first_runs(
                _PMM_STUB_NAME,
                [_MYSQL_STUB_NAME],
                [_StubPMMSyncer(), _StubMySQLSyncer()],
            )

        (record,) = [r for r in caplog.records if r.levelno == logging.ERROR]
        assert record.exc_info is not None
        assert _MYSQL_STUB_NAME in record.getMessage()


async def _assert_the_leader_run_starts_its_follower(
    maker: async_sessionmaker[AsyncSession], mocker, mock_remote_api
) -> None:
    """Run the leader through the public call and check it starts the follower.

    The kick is gated on the leader's completed pass, read through a session of its
    own. On a fresh database only the run this call makes can satisfy that gate, so
    a kick at all proves the pass was persisted before the gate read it.
    """
    _route_sessions(mocker, maker)
    mocker.patch(
        "app.sep.apps.inventory.sync.get_syncers_standalone",
        return_value=[
            _LeaderSyncer(inventory_api=mock_remote_api),
            _FollowerSyncer(inventory_api=mock_remote_api),
        ],
    )
    send_task = mocker.patch.object(celery, "send_task")

    await run_scheduled_inventory_sync(syncer=_LEADER, follower_syncers=[_FOLLOWER])

    async with maker() as session:
        assert await SyncItemManager.inventory_sync_completed(session, _LEADER)
        assert await SyncInstanceManager.list(session, syncer=_FOLLOWER) == []
    send_task.assert_called_once_with(
        EXECUTE_TASK_BY_NAME_TASK, kwargs=_follower_kick(_FOLLOWER, _LEADER)
    )


@pytest.mark.asyncio
async def test_the_leader_run_starts_its_never_run_follower(
    sep_maker, mocker, mock_remote_api
):
    """Start the follower after the leader's real run, on SQLite."""
    await _assert_the_leader_run_starts_its_follower(sep_maker, mocker, mock_remote_api)


@pytest.mark.postgres
@pytest.mark.asyncio
async def test_the_leader_run_starts_its_never_run_follower_on_postgres(
    postgres_session_maker, mocker, mock_remote_api
):
    """Start the follower after the leader's real run, across PostgreSQL connections.

    SQLite's ``StaticPool`` shares one connection between the run and the gate, so
    only here does the gate prove the leader's pass was committed, not just written.
    """
    await _assert_the_leader_run_starts_its_follower(
        postgres_session_maker, mocker, mock_remote_api
    )

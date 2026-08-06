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

import re
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

from app.core.config import settings
from app.sep.apps.inventory.sync import (
    run_inventory_sync,
    run_node_sync,
    run_scheduled_inventory_sync,
    run_schema_sync,
    run_service_sync,
    run_table_sync,
)
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService, CreatedTable
from app.sep.sync.models import BaseSyncer
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

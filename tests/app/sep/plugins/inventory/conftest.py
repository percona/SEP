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

"""Shared fixtures for the inventory plugin test suite.

Hoisted from ``test_routes.py`` so the JSON API tests under
``test_api_routes.py`` can reuse the same syncer stubs, the
``SyncItemManager.sync_is_running`` patch, and the
``run_*_sync`` patches without re-declaring them.
"""

from collections.abc import Iterator
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import BackgroundTasks
from pytest_mock import MockerFixture

from app.sep.crud import SyncItemManager
from app.sep.inventory import CreatedNode, CreatedSchema, CreatedService
from app.sep.main import sep_app
from app.sep.plugins.inventory.deps import get_syncers


class _StubPMMSyncer:
    """Stand in for a PMM syncer; capability checks default to ``True``."""

    def can_sync_inventory(self) -> bool:
        return True

    def can_sync_node(self, node: CreatedNode) -> bool:
        return True

    def can_sync_service(self, service: CreatedService) -> bool:
        return True

    def can_sync_schema(self, schema: CreatedSchema) -> bool:
        return True


class _StubMySQLSyncer:
    """Stand in for a MySQL syncer; capability checks default to ``True``."""

    def can_sync_inventory(self) -> bool:
        return True

    def can_sync_node(self, node: CreatedNode) -> bool:
        return True

    def can_sync_service(self, service: CreatedService) -> bool:
        return True

    def can_sync_schema(self, schema: CreatedSchema) -> bool:
        return True


_PMM_STUB_NAME = f"{_StubPMMSyncer.__module__}.{_StubPMMSyncer.__name__}"
_MYSQL_STUB_NAME = f"{_StubMySQLSyncer.__module__}.{_StubMySQLSyncer.__name__}"
_EXPECTED_STUB_COUNT = 2


def _no_syncers() -> list:
    """Resolve ``SyncersDep`` to an empty list for the no-syncers test path."""
    return []


@pytest.fixture
def mock_sync_item_manager(mocker: MockerFixture) -> AsyncMock:
    """Mock the SyncItemManager sync_is_running method."""
    return mocker.patch.object(
        SyncItemManager, "sync_is_running", new=AsyncMock(return_value=False)
    )


@pytest.fixture
def mock_syncers() -> Iterator[list]:
    """Override the SyncersDep with two stub syncers."""
    stubs = [_StubPMMSyncer(), _StubMySQLSyncer()]
    sep_app.dependency_overrides[get_syncers] = lambda: stubs
    yield stubs
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_background_tasks() -> Iterator[MagicMock]:
    """Mock the BackgroundTasks dependency."""
    mock = MagicMock(spec=BackgroundTasks)
    sep_app.dependency_overrides[BackgroundTasks] = lambda: mock
    yield mock
    sep_app.dependency_overrides = {}


@pytest.fixture
def mock_run_sync_funcs(mocker: MockerFixture) -> dict[str, AsyncMock]:
    """Replace the ``run_*_sync`` symbols on the routes/api_routes modules.

    The real background-task callables open database sessions and invoke
    ``syncer.api_auth(...)``, which the lightweight stub syncers cannot
    satisfy. Patching them at both the Jinja2 ``routes`` and JSON-API
    ``api_routes`` module level lets the real ``BackgroundTasks`` instance
    schedule and execute the mocks immediately after the response, capturing
    the args originally passed to ``add_task``.
    """
    inventory_mock = AsyncMock()
    node_mock = AsyncMock()
    service_mock = AsyncMock()
    schema_mock = AsyncMock()
    mocker.patch(
        "app.sep.plugins.inventory.routes.run_inventory_sync",
        new=inventory_mock,
    )
    mocker.patch(
        "app.sep.plugins.inventory.routes.run_node_sync",
        new=node_mock,
    )
    mocker.patch(
        "app.sep.plugins.inventory.routes.run_service_sync",
        new=service_mock,
    )
    mocker.patch(
        "app.sep.plugins.inventory.routes.run_schema_sync",
        new=schema_mock,
    )
    # The JSON API trigger imports ``run_inventory_sync`` into the
    # ``api_routes`` module namespace; patch that alias too so API-route
    # tests can reuse the same fixture. ``create=True`` keeps this safe
    # during early TDD iterations when the import has not yet landed.
    mocker.patch(
        "app.sep.plugins.inventory.api_routes.run_inventory_sync",
        new=inventory_mock,
        create=True,
    )
    return {
        "inventory": inventory_mock,
        "node": node_mock,
        "service": service_mock,
        "schema": schema_mock,
    }

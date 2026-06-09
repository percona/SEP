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

"""Tests for the SEP override rebind callbacks wired in ``app.sep.main``."""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from pytest_mock import MockerFixture

from app.core.config import PMMSettings, Settings, settings
from app.core.requests import RemoteAPI
from app.sep.config import sep_settings
from app.sep.main import _invalidate_pmm_clients, _make_remote_api_rebinder


@pytest.mark.asyncio
async def test_endpoint_rebinder_swaps_app_state_client() -> None:
    """The rebinder opens a client on the new endpoint and drains the old one."""
    app = FastAPI()
    old = await RemoteAPI(endpoint="https://old-inv.example.org").open()
    app.state.inventory_api = old
    sep_settings._set_snapshot({"INVENTORY_ENDPOINT": "https://new-inv.example.org"})

    rebind = _make_remote_api_rebinder(
        app, "inventory_api", lambda: sep_settings.INVENTORY_ENDPOINT
    )
    await rebind({})

    new = app.state.inventory_api
    try:
        assert new is not old
        assert str(new.endpoint).startswith("https://new-inv.example.org")
        assert old._session is None  # the previous client was drained
    finally:
        await new.close()


@pytest.mark.asyncio
async def test_endpoint_rebinder_invalidates_when_no_app_state_client(
    mocker: MockerFixture,
) -> None:
    """Without an ``app.state`` client, the rebinder evicts the registry client."""
    app = FastAPI()
    sep_settings._set_snapshot({"INVENTORY_ENDPOINT": "https://new-inv.example.org"})
    invalidate = mocker.patch.object(Settings, "invalidate_client", new=AsyncMock())

    rebind = _make_remote_api_rebinder(
        app, "inventory_api", lambda: sep_settings.INVENTORY_ENDPOINT
    )
    await rebind({})

    invalidate.assert_awaited_once_with("https://new-inv.example.org")


@pytest.mark.asyncio
async def test_invalidate_pmm_clients_evicts_current_pmm_endpoint(
    mocker: MockerFixture,
) -> None:
    """The PMM callback evicts cached clients on the overridden PMM endpoint."""
    settings._set_snapshot({"PMM": PMMSettings(endpoint="https://new-pmm.example.org")})
    invalidate = mocker.patch.object(Settings, "invalidate_client", new=AsyncMock())

    await _invalidate_pmm_clients({})

    invalidate.assert_awaited_once_with("https://new-pmm.example.org")


@pytest.mark.asyncio
async def test_invalidate_pmm_clients_noop_without_endpoint(
    mocker: MockerFixture,
) -> None:
    """The PMM callback is a no-op when no PMM endpoint is configured."""
    settings._set_snapshot({"PMM": PMMSettings(endpoint=None)})
    invalidate = mocker.patch.object(Settings, "invalidate_client", new=AsyncMock())

    await _invalidate_pmm_clients({})

    invalidate.assert_not_awaited()

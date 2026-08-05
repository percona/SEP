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
from sqlalchemy_celery_beat.models import Period

import app.sep.main as sep_main
from app.core.celery.models import IntervalSchedule
from app.core.config import PMMSettings, Settings, settings
from app.core.requests import RemoteAPI
from app.core.settings_override.models import SettingClassEnum
from app.sep.config import sep_settings
from app.sep.main import (
    _make_remote_api_rebinder,
    _reseed_system_periodic_tasks,
)
from app.sep.settings_override import apply_logging_dictconfig, invalidate_pmm_clients
from app.sep.snippets.config import snippets_settings


@pytest.mark.asyncio
async def test_endpoint_rebinder_swaps_app_state_client() -> None:
    """Assert the rebinder opens a client on the new endpoint and drains the old one."""
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
    """Assert the rebinder evicts the registry client when no ``app.state`` client exists."""
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
    """Assert the PMM callback evicts cached clients on the overridden PMM endpoint."""
    settings._set_snapshot({"PMM": PMMSettings(endpoint="https://new-pmm.example.org")})
    invalidate = mocker.patch.object(Settings, "invalidate_client", new=AsyncMock())

    await invalidate_pmm_clients({})

    invalidate.assert_awaited_once_with("https://new-pmm.example.org")


@pytest.mark.asyncio
async def test_invalidate_pmm_clients_noop_without_endpoint(
    mocker: MockerFixture,
) -> None:
    """Assert the PMM callback is a no-op when no PMM endpoint is configured."""
    settings._set_snapshot({"PMM": PMMSettings(endpoint=None)})
    invalidate = mocker.patch.object(Settings, "invalidate_client", new=AsyncMock())

    await invalidate_pmm_clients({})

    invalidate.assert_not_awaited()


@pytest.mark.asyncio
async def test_reseed_callback_reseeds_beat_with_live_interval(
    mocker: MockerFixture,
) -> None:
    """Assert the snippets callback re-seeds the beat schedule from the live interval.

    It rebuilds the task set (reading the overridden ``SYNC_INTERVAL`` from the
    proxy snapshot) and re-invokes ``init_periodic_tasks_db`` under the ``sep__``
    prefix, so the ``sep__sync_snippets`` beat row reflects the new cadence on
    beat's next tick.
    """
    reseed = mocker.patch("app.sep.main.init_periodic_tasks_db", new_callable=AsyncMock)
    snippets_settings._set_snapshot(
        {"SYNC_INTERVAL": IntervalSchedule(every=15, period=Period.MINUTES)}
    )
    try:
        await _reseed_system_periodic_tasks({})
    finally:
        snippets_settings._set_snapshot({})

    reseed.assert_awaited_once()
    tasks, prefix = reseed.await_args.args
    assert prefix == "sep__"
    snippets = next(
        schedule
        for schedule in tasks
        for task in schedule.tasks
        if task.name == "sep__sync_snippets"
    )
    assert snippets.schedule == IntervalSchedule(every=15, period=Period.MINUTES)


@pytest.mark.asyncio
async def test_reseed_callback_registered_for_sync_interval() -> None:
    """Assert ``sep_overrides_lifespan`` registers the snippets-interval re-seed callback."""
    original = getattr(sep_main.sep_app.state, "override_callbacks", None)
    try:
        async with sep_main.sep_overrides_lifespan(FastAPI()):
            callbacks = sep_main.sep_app.state.override_callbacks
        assert (
            SettingClassEnum.SNIPPETS_SETTINGS,
            "SYNC_INTERVAL",
        ) in callbacks
        assert (
            callbacks[(SettingClassEnum.SNIPPETS_SETTINGS, "SYNC_INTERVAL")]
            is sep_main._reseed_system_periodic_tasks
        )
    finally:
        sep_main.sep_app.state.override_callbacks = original


@pytest.mark.asyncio
async def test_apply_logging_dictconfig_reapplies_new_level(
    mocker: MockerFixture,
) -> None:
    """Assert the LOGGING rebind re-applies ``dictConfig`` with the live level.

    ``LOGGING`` is HOT but ``LOGGING_CONFIG`` is not, so the callback must inject
    the overridden level into the config before re-applying it — otherwise the
    stale level baked in at construction time would be re-applied.
    """
    dict_config = mocker.patch("app.sep.settings_override.logging.config.dictConfig")
    settings._set_snapshot({"LOGGING": "DEBUG"})
    try:
        await apply_logging_dictconfig({})
    finally:
        settings._set_snapshot({})

    dict_config.assert_called_once()
    applied = dict_config.call_args.args[0]
    assert applied["loggers"][""]["level"] == "DEBUG"
    assert applied["loggers"]["app"]["level"] == "DEBUG"


@pytest.mark.asyncio
async def test_apply_logging_dictconfig_swallows_failure(
    mocker: MockerFixture,
) -> None:
    """Assert a malformed logging config is logged and swallowed, never crashing the app."""
    mocker.patch(
        "app.sep.settings_override.logging.config.dictConfig",
        side_effect=ValueError("bad config"),
    )
    settings._set_snapshot({"LOGGING": "DEBUG"})
    try:
        # Must not raise.
        await apply_logging_dictconfig({})
    finally:
        settings._set_snapshot({})


@pytest.mark.asyncio
async def test_logging_and_app_drain_callbacks_registered() -> None:
    """Assert the LOGGING rebind and the APP_DRAIN reseed callback are registered."""
    original = getattr(sep_main.sep_app.state, "override_callbacks", None)
    try:
        async with sep_main.sep_overrides_lifespan(FastAPI()):
            callbacks = sep_main.sep_app.state.override_callbacks
        assert (
            callbacks[(SettingClassEnum.SETTINGS, "LOGGING")]
            is apply_logging_dictconfig
        )
        assert (
            callbacks[(SettingClassEnum.SEP_SETTINGS, "APP_DRAIN")]
            is sep_main._reseed_system_periodic_tasks
        )
    finally:
        sep_main.sep_app.state.override_callbacks = original

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

"""Tests for the background snapshot-refresher."""

import asyncio
from datetime import timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.lifecycle import (
    ProxyEntry,
    refresh_all,
    start_refresh_task,
)
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import SettingClassEnum, SettingOverride
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.utils import json_serializer
from app.sep.config import SEPSettings


@pytest_asyncio.fixture(name="session_maker")
async def session_maker_fixture() -> async_sessionmaker:
    """Provide an in-memory SQLite session maker bound to a fresh schema."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    return get_async_session_maker_from_engine(engine)


def _make_proxies() -> tuple[OverridableSettingsProxy, dict]:
    """Construct an SEP proxy and a registry mapping for refresh tests."""
    proxy: OverridableSettingsProxy = OverridableSettingsProxy(
        SEPSettings, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    registry = {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(proxy, SEPSettings),
    }
    return proxy, registry


@pytest.mark.asyncio
async def test_refresh_all_swaps_snapshot(
    session_maker: async_sessionmaker,
) -> None:
    """``refresh_all`` populates the proxy snapshot from the override table."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    async with session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )

    await refresh_all(lambda: session_maker, registry)
    assert proxy.CONNECTIVITY_CHECK_DEFAULT is override_value


@pytest.mark.asyncio
async def test_refresh_all_retains_previous_snapshot_on_error(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errors during ``build_snapshot`` keep the previous snapshot intact."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    proxy._set_snapshot({"CONNECTIVITY_CHECK_DEFAULT": override_value})

    async def _boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr("app.core.settings_override.lifecycle.build_snapshot", _boom)
    await refresh_all(lambda: session_maker, registry)
    # Previous snapshot is retained -- the refresh did not clobber it.
    assert proxy.CONNECTIVITY_CHECK_DEFAULT is override_value


@pytest.mark.asyncio
async def test_start_refresh_task_runs_initial_load(
    session_maker: async_sessionmaker,
) -> None:
    """``start_refresh_task`` awaits an initial refresh before returning the task."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    async with session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )

    task = await start_refresh_task(
        lambda: session_maker, registry, interval=timedelta(seconds=3600)
    )
    try:
        assert proxy.CONNECTIVITY_CHECK_DEFAULT is override_value
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_refresh_task_cancellable(
    session_maker: async_sessionmaker,
) -> None:
    """The background task is cancellable and shuts down cleanly."""
    _proxy, registry = _make_proxies()
    task = await start_refresh_task(
        lambda: session_maker, registry, interval=timedelta(seconds=3600)
    )
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.cancelled()


@pytest.mark.asyncio
async def test_refresh_picks_up_changes_on_next_cycle(
    session_maker: async_sessionmaker,
) -> None:
    """Adding an override row between cycles becomes visible after the next refresh."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    task = await start_refresh_task(
        lambda: session_maker, registry, interval=timedelta(milliseconds=50)
    )
    try:
        async with session_maker() as session:
            await SettingsOverrideManager.create(
                session,
                SettingOverride(
                    setting_class=SettingClassEnum.SEP_SETTINGS,
                    key="CONNECTIVITY_CHECK_DEFAULT",
                    value=override_value,
                ),
            )
        for _ in range(50):
            await asyncio.sleep(0.05)
            try:
                if proxy.CONNECTIVITY_CHECK_DEFAULT is override_value:
                    return
            except AttributeError:
                continue
        pytest.fail("Refresher did not observe the inserted override row")
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

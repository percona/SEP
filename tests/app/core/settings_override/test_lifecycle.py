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
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel.pool import StaticPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.cache import build_snapshot
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
from app.tasks.config import tasks_settings, TasksSettings
from app.tasks.execution.executors.nomad import NomadExecutor
from app.tasks.execution.nomad_lifecycle import NomadLifecycle
from app.tasks.main import _reconcile_nomad, tasks_app
from tests.app.core.settings_override.conftest import hanging_session_maker_factory


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
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


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
async def test_refresh_all_rolls_back_session_between_proxies(
    session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-cycle failure rolls the session back so the next proxy can still load.

    Without the rollback, Postgres would leave the session in
    ``InFailedSqlTransaction`` after the first proxy's failed query and
    every subsequent proxy on the same session would also fail. SQLite
    doesn't reproduce that aborted-tx state, so we simulate it by spying
    on ``session.rollback`` and asserting it fires between proxies, and by
    making the first proxy fail while asserting the second still picks up
    its row from the DB.
    """
    sep_proxy: OverridableSettingsProxy = OverridableSettingsProxy(
        SEPSettings, setting_class=SettingClassEnum.SEP_SETTINGS
    )
    tasks_proxy: OverridableSettingsProxy = OverridableSettingsProxy(
        TasksSettings, setting_class=SettingClassEnum.TASKS_SETTINGS
    )
    registry = {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(sep_proxy, SEPSettings),
        SettingClassEnum.TASKS_SETTINGS: ProxyEntry(tasks_proxy, TasksSettings),
    }
    tasks_override = 7200
    async with session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.TASKS_SETTINGS,
                key="STALENESS_THRESHOLD_SECONDS",
                value=tasks_override,
            ),
        )

    real_build_snapshot = build_snapshot
    call_count = {"n": 0}

    async def _fail_first(
        session: object,
        settings_cls: type,
        base_settings: object = None,
    ) -> object:
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("first proxy explodes mid-cycle")
        return await real_build_snapshot(session, settings_cls, base_settings)

    monkeypatch.setattr(
        "app.core.settings_override.lifecycle.build_snapshot", _fail_first
    )

    rollback_calls = {"n": 0}
    real_rollback = AsyncSession.rollback

    async def _counting_rollback(self: AsyncSession) -> None:
        rollback_calls["n"] += 1
        await real_rollback(self)

    monkeypatch.setattr(AsyncSession, "rollback", _counting_rollback)

    await refresh_all(lambda: session_maker, registry)

    assert rollback_calls["n"] >= 1, "session.rollback() was not called after failure"
    # Second proxy must have loaded successfully after the rollback -- the
    # failure on proxy 1 must NOT block the manager.list() call on proxy 2.
    assert tasks_override == tasks_proxy.STALENESS_THRESHOLD_SECONDS


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
async def test_start_refresh_task_seed_timeout_returns_within_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Bound a hanging seed, keep the periodic task, and log expiry at ERROR."""
    _proxy, registry = _make_proxies()
    seed_timeout = 0.05

    with caplog.at_level("ERROR", logger="app.core.settings_override.lifecycle"):
        task = await asyncio.wait_for(
            start_refresh_task(
                hanging_session_maker_factory,
                registry,
                interval=timedelta(seconds=3600),
                seed_timeout=seed_timeout,
            ),
            timeout=1.0,
        )
    try:
        assert not task.done()
        assert any(
            record.levelname == "ERROR"
            and f"{seed_timeout:.2f}s" in record.message
            and "unseeded" in record.message
            for record in caplog.records
        )
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_refresh_task_without_seed_timeout_awaits_the_seed(
    session_maker: async_sessionmaker,
) -> None:
    """Keep today's unbounded seed when no budget is supplied."""
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


_CALLBACK_KEY = (SettingClassEnum.SEP_SETTINGS, "CONNECTIVITY_CHECK_DEFAULT")
_NOMAD_CALLBACK_KEY = (SettingClassEnum.TASKS_SETTINGS, "NOMAD")
_NOMAD_LEAF_TIMEOUT = 30


def _make_tasks_proxy_registry() -> tuple[OverridableSettingsProxy, dict]:
    """Construct the global Tasks proxy and a single-entry registry."""
    registry = {
        SettingClassEnum.TASKS_SETTINGS: ProxyEntry(tasks_settings, TasksSettings),
    }
    return tasks_settings, registry


async def _seed_nomad_timeout_override(
    session_maker: async_sessionmaker, *, value: int = _NOMAD_LEAF_TIMEOUT
) -> None:
    """Insert a ``NOMAD__TIMEOUT`` per-leaf override row."""
    async with session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.TASKS_SETTINGS,
                key="NOMAD__TIMEOUT",
                value=value,
            ),
        )


async def _seed_connectivity_override(
    session_maker: async_sessionmaker, *, value: bool
) -> None:
    """Insert a ``CONNECTIVITY_CHECK_DEFAULT`` override row."""
    async with session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=SettingClassEnum.SEP_SETTINGS,
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=value,
            ),
        )


@pytest.mark.asyncio
async def test_refresh_all_nomad_reconcile_stable_under_per_leaf_override(
    session_maker: async_sessionmaker,
) -> None:
    """Record reconcile-churn under an active per-child ``NOMAD`` override.

    A per-leaf override stores a merged
    ``NomadExecutor`` in the snapshot (not a fingerprint dict). Each
    ``build_snapshot`` produces a fresh instance, but Pydantic field equality
    makes consecutive snapshots compare equal, so ``fire_change_callbacks`` does
    **not** notify ``_reconcile_nomad`` on every cycle when the effective config
    is unchanged. When a callback does fire,
    :meth:`NomadLifecycle.reconcile` compares ``model_dump(mode="json")`` and
    does not rebuild the entered executor.
    """
    tasks_settings._set_snapshot({})
    try:
        await _seed_nomad_timeout_override(session_maker)
        _proxy, registry = _make_tasks_proxy_registry()

        # Seed the override snapshot without firing rebind callbacks.
        await refresh_all(lambda: session_maker, registry)

        app = FastAPI()
        reconcile_calls = 0

        async with NomadLifecycle(app) as holder:
            executor_before = holder.current
            real_reconcile = holder.reconcile

            async def _counting_reconcile() -> None:
                nonlocal reconcile_calls
                reconcile_calls += 1
                await real_reconcile()

            holder.reconcile = _counting_reconcile

            tasks_app.state.nomad_lifecycle = holder
            try:
                # Baseline refresh under the live holder (not counted).
                await refresh_all(lambda: session_maker, registry)
                snapshot_before = dict(tasks_settings.get_snapshot())
                executor_after_baseline = holder.current

                # Measure one further cycle with rebind callbacks wired.
                await refresh_all(
                    lambda: session_maker,
                    registry,
                    {_NOMAD_CALLBACK_KEY: _reconcile_nomad},
                )
                snapshot_after = dict(tasks_settings.get_snapshot())
                executor_after = holder.current
            finally:
                tasks_app.state.nomad_lifecycle = None

        nomad_before = snapshot_before["NOMAD"]
        nomad_after = snapshot_after["NOMAD"]
        assert isinstance(nomad_before, NomadExecutor)
        assert isinstance(nomad_after, NomadExecutor)
        assert nomad_before.timeout == _NOMAD_LEAF_TIMEOUT
        assert nomad_after.timeout == _NOMAD_LEAF_TIMEOUT

        before_config = nomad_before.model_dump(mode="json")
        after_config = nomad_after.model_dump(mode="json")
        assert before_config == after_config

        # Fresh merged instances compare equal on declared fields, so callbacks
        # stay quiet; if equality ever regresses, reconcile must still no-op.
        snapshots_compare_equal = nomad_before == nomad_after
        assert snapshots_compare_equal

        # reconcile's JSON guard must keep the live entered executor stable.
        assert executor_before is executor_after_baseline
        assert executor_after_baseline is executor_after
        assert reconcile_calls == 0
    finally:
        tasks_settings._set_snapshot({})


@pytest.mark.asyncio
async def test_refresh_all_fires_callback_for_changed_key(
    session_maker: async_sessionmaker,
) -> None:
    """A callback fires for a key whose value changed between snapshots."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    await _seed_connectivity_override(session_maker, value=override_value)
    fired = []

    async def _callback(_: object) -> None:
        fired.append(True)

    await refresh_all(lambda: session_maker, registry, {_CALLBACK_KEY: _callback})
    assert fired == [True]
    assert proxy.CONNECTIVITY_CHECK_DEFAULT is override_value


@pytest.mark.asyncio
async def test_refresh_all_skips_callback_for_unchanged_key(
    session_maker: async_sessionmaker,
) -> None:
    """A callback does not fire when its key's value is unchanged."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    await _seed_connectivity_override(session_maker, value=override_value)
    await refresh_all(lambda: session_maker, registry)
    fired = []

    async def _callback(_: object) -> None:
        fired.append(True)

    await refresh_all(lambda: session_maker, registry, {_CALLBACK_KEY: _callback})
    assert fired == []


@pytest.mark.asyncio
async def test_refresh_all_isolates_callback_exception(
    session_maker: async_sessionmaker,
) -> None:
    """A raising callback is caught; the snapshot is still published."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    await _seed_connectivity_override(session_maker, value=override_value)

    async def _boom(_: object) -> None:
        raise RuntimeError("callback boom")

    await refresh_all(lambda: session_maker, registry, {_CALLBACK_KEY: _boom})
    assert proxy.CONNECTIVITY_CHECK_DEFAULT is override_value


@pytest.mark.asyncio
async def test_start_refresh_task_initial_does_not_fire_callbacks(
    session_maker: async_sessionmaker,
) -> None:
    """The initial inline refresh publishes the snapshot but fires no callback."""
    proxy, registry = _make_proxies()
    override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
    await _seed_connectivity_override(session_maker, value=override_value)
    fired = []

    async def _callback(_: object) -> None:
        fired.append(True)

    task = await start_refresh_task(
        lambda: session_maker,
        registry,
        interval=timedelta(seconds=3600),
        callbacks={_CALLBACK_KEY: _callback},
    )
    try:
        assert proxy.CONNECTIVITY_CHECK_DEFAULT is override_value
        assert fired == []
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_start_refresh_task_fires_callback_on_loop_change(
    session_maker: async_sessionmaker,
) -> None:
    """A change inserted after startup fires the callback on a later loop cycle."""
    proxy, registry = _make_proxies()
    fired = asyncio.Event()

    async def _callback(_: object) -> None:
        fired.set()

    task = await start_refresh_task(
        lambda: session_maker,
        registry,
        interval=timedelta(milliseconds=50),
        callbacks={_CALLBACK_KEY: _callback},
    )
    try:
        assert not fired.is_set()
        override_value = not SEPSettings().CONNECTIVITY_CHECK_DEFAULT
        await _seed_connectivity_override(session_maker, value=override_value)
        await asyncio.wait_for(fired.wait(), timeout=5)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task


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

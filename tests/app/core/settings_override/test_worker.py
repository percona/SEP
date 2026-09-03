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

"""Tests for the reusable prefork-child settings-override refresher handle."""

import asyncio
from collections.abc import Iterator
from contextlib import suppress
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.lifecycle import (
    CallbackRegistry,
    ProxyEntry,
    ProxyRegistry,
    SnapshotChange,
)
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.worker import SEED_TIMEOUT_FRACTION, WorkerRefresher
from app.core.utils import json_serializer
from app.sep.config import SEPSettings
from app.tasks.config import TasksSettings
from tests.app.core.settings_override.conftest import (
    recording_start_refresh_task,
    START_REFRESH_TASK,
)
from tests.app.db_schema import apply_schema

INTERVAL = timedelta(seconds=30)


async def _noop_callback(_: SnapshotChange) -> None:
    """Accept a snapshot change and do nothing; a stand-in registry entry."""


def _make_registry() -> ProxyRegistry:
    """Compose a two-entry proxy registry over freshly-built proxies."""
    return {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(
            OverridableSettingsProxy(SEPSettings, setting_class=SEPSettings.__name__),
            SEPSettings,
        ),
        SettingClassEnum.TASKS_SETTINGS: ProxyEntry(
            OverridableSettingsProxy(
                TasksSettings, setting_class=TasksSettings.__name__
            ),
            TasksSettings,
        ),
    }


CALLBACKS: CallbackRegistry = {(SettingClassEnum.SETTINGS, "PMM"): _noop_callback}


class _CountingRegistry:
    """Compose the registry through :func:`_make_registry`, counting each build."""

    def __init__(self) -> None:
        self.builds = 0

    def __call__(self) -> ProxyRegistry:
        self.builds += 1
        return _make_registry()


def _unreachable_loop() -> asyncio.AbstractEventLoop:
    """Fail the test if the refresher resolves the event loop."""
    raise AssertionError("the event loop must not be resolved")


def _unreachable_session_maker() -> async_sessionmaker:
    """Fail the test if the refresher resolves the session maker."""
    raise AssertionError("the session maker must not be resolved")


@pytest.fixture(name="loop")
def loop_fixture() -> Iterator[asyncio.AbstractEventLoop]:
    """Provide a dedicated event loop standing in for a prefork child's."""
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(name="session_maker")
def session_maker_fixture(
    loop: asyncio.AbstractEventLoop,
) -> Iterator[async_sessionmaker]:
    """Provide an in-memory SQLite session maker driven through ``loop``."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )

    async def _create_schema() -> None:
        async with engine.begin() as conn:
            await apply_schema(conn, SQLModel.metadata)

    loop.run_until_complete(_create_schema())
    yield get_async_session_maker_from_engine(engine)
    loop.run_until_complete(engine.dispose())


class TestWorkerRefresherStart:
    """Cover the start path: the enabled gate, idempotency, and late resolution."""

    def test_start_creates_a_task_on_the_resolved_loop(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Run the refresher on the loop the getter returns."""
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)

        refresher.start(INTERVAL, enabled=True)

        try:
            assert refresher.task is not None
            assert refresher.task.get_loop() is loop
        finally:
            refresher.stop()

    def test_disabled_starts_no_task_and_builds_no_registry(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Skip the proxy registry entirely when the refresher is disabled."""
        registry = _CountingRegistry()
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, registry)

        refresher.start(INTERVAL, enabled=False)

        assert refresher.task is None
        assert registry.builds == 0

    def test_construction_does_not_build_the_registry(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Defer the registry build past construction of the singleton."""
        registry = _CountingRegistry()

        WorkerRefresher(lambda: loop, lambda: session_maker, registry)

        assert registry.builds == 0

    def test_second_start_keeps_the_running_task(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Return early on re-entry rather than leaking a second task."""
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)
        refresher.start(INTERVAL, enabled=True)
        first = refresher.task

        refresher.start(INTERVAL, enabled=True)

        try:
            assert refresher.task is first
            assert not first.done()
        finally:
            refresher.stop()

    def test_second_start_does_not_rebuild_the_registry(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Skip the registry build on a start that short-circuits."""
        registry = _CountingRegistry()
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, registry)
        refresher.start(INTERVAL, enabled=True)

        refresher.start(INTERVAL, enabled=True)

        try:
            assert registry.builds == 1
        finally:
            refresher.stop()

    def test_start_after_the_task_finished_creates_a_new_task(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Replace a finished task instead of leaving the child unrefreshed."""
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)
        refresher.start(INTERVAL, enabled=True)
        finished = refresher.task
        finished.cancel()
        with suppress(asyncio.CancelledError):
            loop.run_until_complete(finished)

        refresher.start(INTERVAL, enabled=True)

        try:
            assert refresher.task is not finished
            assert not refresher.task.done()
        finally:
            refresher.stop()

    def test_start_resolves_its_dependencies_at_call_time(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Read the loop and session maker rebound after construction.

        Mirrors the prefork child, where ``init_child_event_loop`` replaces the
        loop and the tests rebind the session maker, both after the module-level
        singleton was constructed.
        """
        stale_loop = asyncio.new_event_loop()
        current_loop = stale_loop
        current_session_maker = None
        refresher = WorkerRefresher(
            lambda: current_loop,
            lambda: current_session_maker,
            _make_registry,
        )
        current_loop = loop
        current_session_maker = session_maker

        refresher.start(INTERVAL, enabled=True)

        try:
            assert refresher.task.get_loop() is loop
        finally:
            refresher.stop()
            stale_loop.close()

    @pytest.mark.parametrize(
        ("start_kwargs", "expected"),
        [
            pytest.param({"callbacks": CALLBACKS}, CALLBACKS, id="registry-forwarded"),
            pytest.param({}, None, id="omitted-defaults-to-none"),
        ],
    )
    def test_start_hands_the_callback_registry_to_the_refresh_task(
        self,
        loop: asyncio.AbstractEventLoop,
        session_maker: async_sessionmaker,
        monkeypatch: pytest.MonkeyPatch,
        start_kwargs: dict[str, CallbackRegistry],
        expected: CallbackRegistry | None,
    ) -> None:
        """Forward the caller's callbacks, passing ``None`` when none are given."""
        recorded: dict[str, object] = {}
        monkeypatch.setattr(START_REFRESH_TASK, recording_start_refresh_task(recorded))
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)

        refresher.start(INTERVAL, enabled=True, **start_kwargs)

        try:
            assert recorded["callbacks"] is expected
        finally:
            refresher.stop()

    @pytest.mark.parametrize(
        ("proc_alive_timeout", "expected_seed_timeout"),
        [
            pytest.param(
                4.0,
                4.0 * SEED_TIMEOUT_FRACTION,
                id="derived-from-deadline",
            ),
            pytest.param(None, None, id="unset-leaves-unbounded"),
        ],
    )
    def test_start_forwards_seed_timeout_from_proc_alive_timeout(
        self,
        loop: asyncio.AbstractEventLoop,
        session_maker: async_sessionmaker,
        monkeypatch: pytest.MonkeyPatch,
        proc_alive_timeout: float | None,
        expected_seed_timeout: float | None,
    ) -> None:
        """Apply the safety fraction once in ``start``, or omit when unset."""
        recorded: dict[str, object] = {}
        monkeypatch.setattr(START_REFRESH_TASK, recording_start_refresh_task(recorded))
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)
        start_kwargs = (
            {"proc_alive_timeout": proc_alive_timeout}
            if proc_alive_timeout is not None
            else {}
        )

        refresher.start(INTERVAL, enabled=True, **start_kwargs)

        try:
            if expected_seed_timeout is None:
                assert recorded["seed_timeout"] is None
            else:
                assert recorded["seed_timeout"] == pytest.approx(expected_seed_timeout)
        finally:
            refresher.stop()


class TestWorkerRefresherStop:
    """Cover the shutdown path: cancel, drain, and the never-started no-op."""

    def test_stop_cancels_drains_and_clears_the_task(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Cancel the task, swallow its ``CancelledError``, and clear the handle."""
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)
        refresher.start(INTERVAL, enabled=True)
        task = refresher.task

        refresher.stop()

        assert refresher.task is None
        assert task.cancelled()

    def test_stop_without_start_resolves_nothing(self) -> None:
        """Return without touching the loop when no task was ever started."""
        refresher = WorkerRefresher(
            _unreachable_loop, _unreachable_session_maker, _make_registry
        )

        refresher.stop()

        assert refresher.task is None

    def test_stop_after_the_task_finished_clears_the_handle(
        self, loop: asyncio.AbstractEventLoop, session_maker: async_sessionmaker
    ) -> None:
        """Treat cancelling an already-finished task as harmless."""
        refresher = WorkerRefresher(lambda: loop, lambda: session_maker, _make_registry)
        refresher.start(INTERVAL, enabled=True)
        task = refresher.task
        task.cancel()
        with suppress(asyncio.CancelledError):
            loop.run_until_complete(task)

        refresher.stop()

        assert refresher.task is None

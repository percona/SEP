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

"""Tests for the SEP worker's settings-override wiring."""

import asyncio
import logging
import logging.config
from typing import ClassVar

import pytest
from pydantic import SecretStr
from pytest_mock import MockerFixture
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    AsyncEngine,
    create_async_engine,
)
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app.core.alerts.config import alert_settings, AlertSettings
from app.core.config import BaseYamlSettings, LogLevel, Settings, settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override import lifecycle
from app.core.settings_override.api.routes import AppOwnedClassEntry
from app.core.settings_override.lifecycle import refresh_all
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import (
    setting_class_token,
    SettingClassEnum,
    SettingOverride,
)
from app.core.settings_override.proxy import OverridableSettingsProxy
from app.core.settings_override.registry import hot_field
from app.core.settings_override.worker import SEED_TIMEOUT_FRACTION
from app.core.utils import json_serializer
from app.sep import settings_override as sep_worker
from app.sep.config import sep_settings, SEPSettings
from app.sep.deps import resolve_pmm_api
from app.sep.settings_override import (
    build_sep_override_proxies,
    republish_sep_settings_snapshot,
    start_sep_settings_override_refresher,
    stop_sep_settings_override_refresher,
    WORKER_OVERRIDE_CALLBACKS,
)
from app.tasks.celery import build_tasks_override_proxies
from tests.app.core.settings_override.conftest import (
    HangingSession,
    recording_start_refresh_task,
    START_REFRESH_TASK,
)
from tests.app.db_schema import apply_schema

SEP_CORE_CLASSES = frozenset(
    {
        SettingClassEnum.SEP_SETTINGS,
        SettingClassEnum.SNIPPETS_SETTINGS,
        SettingClassEnum.SETTINGS,
        SettingClassEnum.ALERT_SETTINGS,
    }
)
PMM_ENDPOINT = "https://pmm-worker.example.org"
SEP_OVERRIDE_KEY = "SYNC_REFRESH_TIME"
SEP_OVERRIDE_VALUE = 42
WorkerLoopEnv = tuple[asyncio.AbstractEventLoop, async_sessionmaker]


class _AppOwnedSettings(BaseYamlSettings):
    """Stand in for a settings class an activated app declares.

    :param LABEL: An arbitrary hot field; the builder never reads it.
    """

    SETTINGS_PREFIXES: ClassVar[list[str]] = ["TEST_APP_OWNED"]
    LABEL: str = hot_field("default")


def _app_owned_entry(setting_class: str) -> AppOwnedClassEntry:
    """Build an app-owned registration for ``setting_class``."""
    return AppOwnedClassEntry(
        setting_class=setting_class,
        settings_cls=_AppOwnedSettings,
        proxy=OverridableSettingsProxy(_AppOwnedSettings, setting_class=setting_class),
        app_key="test-app",
    )


async def _create_schema(engine: AsyncEngine) -> None:
    """Create every SQLModel table on ``engine``."""
    async with engine.begin() as conn:
        await apply_schema(conn, SQLModel.metadata)


async def _upsert_override(
    maker: async_sessionmaker,
    *,
    setting_class: str,
    key: str,
    value: object,
) -> None:
    """Insert or replace a single active ``SettingOverride`` row through ``maker``."""
    async with maker() as session:
        await SettingsOverrideManager.delete_where(
            session, setting_class=setting_class, key=key
        )
        await SettingsOverrideManager.create(
            session,
            SettingOverride(setting_class=setting_class, key=key, value=value),
        )


@pytest.fixture(name="no_app_owned_classes")
def no_app_owned_classes_fixture(monkeypatch: pytest.MonkeyPatch) -> None:
    """Compose the SEP registry as if no activated app declared a class."""
    monkeypatch.setattr(sep_worker, "collect_app_owned_settings_classes", list)


@pytest.fixture(name="override_session_maker")
def override_session_maker_fixture() -> async_sessionmaker:
    """Provide an in-memory SQLite session maker with the SEP schema created."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    loop = asyncio.new_event_loop()
    loop.run_until_complete(_create_schema(engine))
    yield get_async_session_maker_from_engine(engine)
    loop.run_until_complete(engine.dispose())
    loop.close()


@pytest.fixture(name="worker_loop_env")
def worker_loop_env_fixture(
    monkeypatch: pytest.MonkeyPatch,
) -> WorkerLoopEnv:
    """Wire a fresh event loop and in-memory SEP DB as a prefork worker child.

    Mirrors the ``worker_process_init`` runtime: a dedicated ``celery.loop``, the
    refresher enabled, ``get_async_session_maker`` pointed at an in-memory
    engine, no app-owned classes, and the per-process refresher reset. Yields
    ``(loop, session_maker)`` and stops any started refresher on teardown.
    """
    loop = asyncio.new_event_loop()
    monkeypatch.setattr(sep_worker.celery, "loop", loop)
    monkeypatch.setattr(sep_worker._refresher, "task", None)
    monkeypatch.setattr(settings.SETTINGS_OVERRIDE, "REFRESHER_ENABLED", True)
    monkeypatch.setattr(sep_worker, "collect_app_owned_settings_classes", list)
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    maker = get_async_session_maker_from_engine(engine)
    monkeypatch.setattr(sep_worker, "get_async_session_maker", lambda: maker)
    loop.run_until_complete(_create_schema(engine))
    yield loop, maker
    stop_sep_settings_override_refresher()
    loop.run_until_complete(engine.dispose())
    loop.close()


class TestBuildSepOverrideProxies:
    """Cover the shared SEP proxy-set builder."""

    @pytest.mark.usefixtures("no_app_owned_classes")
    def test_builder_registers_the_sep_core_classes(self) -> None:
        """Compose exactly SEP's own entries when no app declares one."""
        assert set(build_sep_override_proxies()) == SEP_CORE_CLASSES

    def test_builder_includes_app_owned_entries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Carry an app-declared class alongside SEP's own entries."""
        entry = _app_owned_entry("AlertsSettings")
        monkeypatch.setattr(
            sep_worker, "collect_app_owned_settings_classes", lambda: [entry]
        )

        proxies = build_sep_override_proxies()

        assert set(proxies) == SEP_CORE_CLASSES | {"AlertsSettings"}
        assert proxies["AlertsSettings"].proxy is entry.proxy

    def test_sep_entries_win_over_an_app_owned_collision(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Keep the SEP refresher as the sole owner of a shared core proxy."""
        entry = _app_owned_entry(SettingClassEnum.SETTINGS)
        monkeypatch.setattr(
            sep_worker, "collect_app_owned_settings_classes", lambda: [entry]
        )

        proxies = build_sep_override_proxies()

        assert proxies[SettingClassEnum.SETTINGS].proxy is settings

    @pytest.mark.usefixtures("no_app_owned_classes")
    def test_builder_shares_no_keys_with_the_tasks_registry(self) -> None:
        """Keep the two worker refreshers publishing into disjoint proxy sets.

        A prefork child now runs both, and each resolves against a different
        database, so a shared key would have the two publish over each other.
        Both sides are read from their own builder rather than a literal, so
        adding a class to either one is what moves this assertion.
        """
        assert not set(build_sep_override_proxies()) & set(
            build_tasks_override_proxies()
        )


class TestWorkerOverrideCallbacks:
    """Cover the callback subset the worker refresher registers."""

    def test_registry_is_pmm_and_logging(self) -> None:
        """Pin the disposition: PMM invalidation plus LOGGING dictConfig rebind."""
        assert set(WORKER_OVERRIDE_CALLBACKS) == {
            (SettingClassEnum.SETTINGS, "PMM"),
            (SettingClassEnum.SETTINGS, "LOGGING"),
        }


class TestSepWorkerHandlers:
    """Cover the worker_process_init / worker_process_shutdown SEP handlers."""

    @pytest.mark.usefixtures("worker_loop_env")
    def test_init_starts_a_refresher(self) -> None:
        """Start this child's SEP refresher on ``worker_process_init``."""
        start_sep_settings_override_refresher()

        assert sep_worker._refresher.task is not None

    def test_disabled_starts_no_task(
        self, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        """Start no refresh task when the refresher is disabled."""
        monkeypatch.setattr(settings.SETTINGS_OVERRIDE, "REFRESHER_ENABLED", False)
        monkeypatch.setattr(sep_worker._refresher, "task", None)
        start = mocker.patch("app.core.settings_override.worker.start_refresh_task")

        start_sep_settings_override_refresher()

        start.assert_not_called()
        assert sep_worker._refresher.task is None

    @pytest.mark.usefixtures("worker_loop_env")
    def test_init_is_idempotent_when_already_running(self) -> None:
        """Keep the running refresher and start no second task on re-entry."""
        start_sep_settings_override_refresher()
        first_task = sep_worker._refresher.task

        start_sep_settings_override_refresher()

        assert sep_worker._refresher.task is first_task
        assert not first_task.done()

    @pytest.mark.usefixtures("worker_loop_env")
    def test_shutdown_cancels_and_drains_started_refresher(self) -> None:
        """Stop and drain the started refresher, clearing the handle."""
        start_sep_settings_override_refresher()
        task = sep_worker._refresher.task

        stop_sep_settings_override_refresher()

        assert sep_worker._refresher.task is None
        assert task.cancelled() or task.done()

    def test_shutdown_is_noop_when_not_started(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Handle a never-started refresher as a no-op on shutdown."""
        monkeypatch.setattr(sep_worker._refresher, "task", None)

        stop_sep_settings_override_refresher()

        assert sep_worker._refresher.task is None

    def test_init_seeds_a_sep_override_into_the_worker_proxy(
        self, worker_loop_env: WorkerLoopEnv
    ) -> None:
        """Publish a seeded SEP-side override during the initial inline refresh."""
        loop, maker = worker_loop_env
        loop.run_until_complete(
            _upsert_override(
                maker,
                setting_class=setting_class_token(AlertSettings),
                key="SOURCE_PREFIX",
                value="worker-",
            )
        )

        start_sep_settings_override_refresher()

        assert alert_settings.SOURCE_PREFIX == "worker-"

    def test_init_forwards_a_budget_from_worker_proc_alive_timeout(
        self,
        worker_loop_env: WorkerLoopEnv,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Derive the seed budget from Celery's prefork liveness deadline."""
        recorded: dict[str, object] = {}
        monkeypatch.setattr(START_REFRESH_TASK, recording_start_refresh_task(recorded))
        monkeypatch.setattr(sep_worker.celery.conf, "worker_proc_alive_timeout", 6.0)

        start_sep_settings_override_refresher()

        assert recorded["seed_timeout"] == pytest.approx(6.0 * SEED_TIMEOUT_FRACTION)

    def test_init_returns_with_a_running_refresher_when_the_seed_hangs(
        self,
        worker_loop_env: WorkerLoopEnv,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keep the periodic refresher after a hanging seed hits its budget."""
        monkeypatch.setattr(
            sep_worker, "get_async_session_maker", lambda: HangingSession
        )
        monkeypatch.setattr(sep_worker.celery.conf, "worker_proc_alive_timeout", 0.1)

        start_sep_settings_override_refresher()

        assert sep_worker._refresher.task is not None
        assert not sep_worker._refresher.task.done()


class TestWorkerPmmClientInvalidation:
    """Verify a same-endpoint PMM credential override reaches worker tasks."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("no_app_owned_classes")
    async def test_api_key_only_override_evicts_the_cached_client(
        self, override_session_maker: async_sessionmaker
    ) -> None:
        """Hand a fresh client with the new key to the next ``resolve_pmm_api()``.

        ``ClientRegistry.IMMUTABLE_KEYS`` excludes ``api_key``, so republishing
        the ``PMM`` snapshot alone leaves the stale client cached; only the
        ported invalidation callback evicts it.
        """
        proxies = build_sep_override_proxies()
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(Settings),
            key="PMM",
            value={"endpoint": PMM_ENDPOINT, "api_key": "old-key"},
        )
        await refresh_all(lambda: override_session_maker, proxies)
        stale = await resolve_pmm_api()
        try:
            await _upsert_override(
                override_session_maker,
                setting_class=setting_class_token(Settings),
                key="PMM",
                value={"endpoint": PMM_ENDPOINT, "api_key": "new-key"},
            )

            await refresh_all(
                lambda: override_session_maker, proxies, WORKER_OVERRIDE_CALLBACKS
            )

            fresh = await resolve_pmm_api()
            assert fresh is not stale
            assert fresh.api_key == SecretStr("new-key")
        finally:
            await settings.invalidate_client(PMM_ENDPOINT)

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("no_app_owned_classes")
    async def test_without_the_callback_the_stale_client_survives(
        self, override_session_maker: async_sessionmaker
    ) -> None:
        """Pin the cache gap the ported callback exists to close.

        A refresh cycle carrying no callbacks republishes the ``PMM`` snapshot
        and still hands back the client built with the previous key, because the
        registry key covers endpoint and SSL only.
        """
        proxies = build_sep_override_proxies()
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(Settings),
            key="PMM",
            value={"endpoint": PMM_ENDPOINT, "api_key": "old-key"},
        )
        await refresh_all(lambda: override_session_maker, proxies)
        stale = await resolve_pmm_api()
        try:
            await _upsert_override(
                override_session_maker,
                setting_class=setting_class_token(Settings),
                key="PMM",
                value={"endpoint": PMM_ENDPOINT, "api_key": "new-key"},
            )

            await refresh_all(lambda: override_session_maker, proxies)

            assert settings.PMM.api_key == SecretStr("new-key")
            assert await resolve_pmm_api() is stale
        finally:
            await settings.invalidate_client(PMM_ENDPOINT)

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("no_app_owned_classes")
    async def test_a_failing_callback_does_not_break_the_cycle(
        self,
        override_session_maker: async_sessionmaker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Keep publishing the snapshot when the rebind callback raises."""

        async def _boom(_: object) -> None:
            raise RuntimeError("boom")

        proxies = build_sep_override_proxies()
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(Settings),
            key="PMM",
            value={"endpoint": PMM_ENDPOINT, "api_key": "old-key"},
        )
        await refresh_all(lambda: override_session_maker, proxies)
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(Settings),
            key="PMM",
            value={"endpoint": PMM_ENDPOINT, "api_key": "new-key"},
        )

        await refresh_all(
            lambda: override_session_maker,
            proxies,
            {(SettingClassEnum.SETTINGS, "PMM"): _boom},
        )

        assert settings.PMM.api_key == SecretStr("new-key")


@pytest.fixture(name="worker_logging_boot")
def worker_logging_boot_fixture() -> None:
    """Install a WARNING-level NullHandler config and restore process logging.

    Mutates process-global logging and the ``settings`` snapshot; teardown
    always runs so a leaked ``NullHandler`` root config cannot silence later
    tests. Snapshot restore is belt-and-suspenders with the autouse
    ``_override_snapshot_cleared`` fixture (that one runs only on setup).
    """
    boot_config = {
        "version": 1,
        "disable_existing_loggers": False,
        "handlers": {"default": {"class": "logging.NullHandler"}},
        "loggers": {
            "": {"handlers": ["default"], "level": "WARNING"},
            "app": {"handlers": ["default"], "level": "WARNING", "propagate": False},
        },
    }
    try:
        logging.config.dictConfig(boot_config)
        settings._set_snapshot({"LOGGING": LogLevel.WARNING})
        yield
    finally:
        settings._set_snapshot({})
        logging.config.dictConfig(settings.LOGGING_CONFIG)


class TestWorkerLoggingRebind:
    """Verify a LOGGING override re-applies dictConfig in the worker path."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("no_app_owned_classes", "worker_logging_boot")
    async def test_logging_override_changes_effective_app_level(
        self, override_session_maker: async_sessionmaker
    ) -> None:
        """Raise the worker's app logger to the overridden level on refresh.

        Also pin ``disable_existing_loggers: False``: a runtime logger outside
        the configured logger tree (not under a name ``LOGGING_CONFIG``
        declares) must stay enabled after the callback re-enters ``dictConfig``.
        Children of configured names -- e.g. ``celery.app.trace`` under
        ``celery`` -- are never disabled either way, so they cannot discriminate.
        """
        runtime_logger = logging.getLogger("kombu.connection")
        proxies = build_sep_override_proxies()
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(Settings),
            key="LOGGING",
            value="DEBUG",
        )

        await refresh_all(
            lambda: override_session_maker, proxies, WORKER_OVERRIDE_CALLBACKS
        )

        assert settings.LOGGING == LogLevel.DEBUG
        assert logging.getLogger("app").isEnabledFor(logging.DEBUG)
        assert not runtime_logger.disabled

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("no_app_owned_classes", "worker_logging_boot")
    async def test_without_the_callback_boot_level_survives(
        self, override_session_maker: async_sessionmaker
    ) -> None:
        """Pin the gap: snapshot updates LOGGING but handlers stay at boot level."""
        proxies = build_sep_override_proxies()
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(Settings),
            key="LOGGING",
            value="DEBUG",
        )

        await refresh_all(lambda: override_session_maker, proxies)

        assert settings.LOGGING == LogLevel.DEBUG
        assert not logging.getLogger("app").isEnabledFor(logging.DEBUG)


class TestRepublishSepSettingsSnapshot:
    """Cover the forced republish a task takes before deciding on settings."""

    @pytest.mark.asyncio
    async def test_the_helper_publishes_a_seeded_override(
        self, override_session_maker: async_sessionmaker
    ) -> None:
        """Reflect an override written after the snapshot in hand was built."""
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(SEPSettings),
            key=SEP_OVERRIDE_KEY,
            value=SEP_OVERRIDE_VALUE,
        )

        async with override_session_maker() as session:
            await republish_sep_settings_snapshot(session)

        assert sep_settings.SYNC_REFRESH_TIME == SEP_OVERRIDE_VALUE
        assert sep_settings.get_snapshot()[SEP_OVERRIDE_KEY] == SEP_OVERRIDE_VALUE

    @pytest.mark.asyncio
    async def test_the_helper_fires_no_rebind_callback(
        self, override_session_maker: async_sessionmaker, mocker: MockerFixture
    ) -> None:
        """Publish the changed value without notifying any rebind callback.

        ``publish_snapshot`` has no callback channel, so the diff-and-fire step
        ``refresh_all`` performs never runs, which is why the helper's
        docstring scopes it to callers whose registry watches another class.
        """
        fire = mocker.spy(lifecycle, "fire_change_callbacks")
        await _upsert_override(
            override_session_maker,
            setting_class=setting_class_token(SEPSettings),
            key=SEP_OVERRIDE_KEY,
            value=SEP_OVERRIDE_VALUE,
        )

        async with override_session_maker() as session:
            await republish_sep_settings_snapshot(session)

        assert sep_settings.SYNC_REFRESH_TIME == SEP_OVERRIDE_VALUE
        fire.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_helper_does_not_compose_the_app_owned_registry(
        self, override_session_maker: async_sessionmaker, mocker: MockerFixture
    ) -> None:
        """Publish the one proxy it needs without importing the app tree."""
        collect = mocker.patch.object(
            sep_worker, "collect_app_owned_settings_classes", return_value=[]
        )

        async with override_session_maker() as session:
            await republish_sep_settings_snapshot(session)

        collect.assert_not_called()

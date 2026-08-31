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

"""End-to-end-ish integration tests for the SEP-side override layer."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy_celery_beat.models import PeriodicTask, PeriodicTaskChanged
from sqlmodel import SQLModel
from sqlmodel.pool import StaticPool

from app import main as main_module
from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.models import IntervalSchedule
from app.core.config import settings as core_settings
from app.core.db.utils import get_async_session_maker_from_engine
from app.core.settings_override.lifecycle import ProxyEntry, refresh_all
from app.core.settings_override.manager import SettingsOverrideManager
from app.core.settings_override.models import (
    setting_class_token,
    SettingClassEnum,
    SettingOverride,
)
from app.core.utils import json_serializer
from app.sep.apps.alerts.config import alerts_settings, AlertsSettings
from app.sep.config import sep_settings, SEPSettings
from app.sep.main import _reseed_system_periodic_tasks
from app.sep.snippets.config import snippets_settings, SnippetsSettings
from tests.app.db_schema import apply_schema

SNIPPETS_TASK = "sep__sync_snippets"
RECONCILER_TASK = "sep__reconcile_disabling_apps"
ALERT_BACKUP_TASK = "sep__backup_alert_config"
OVERRIDE_EVERY_MINUTES = 30


@pytest_asyncio.fixture(name="override_session_maker")
async def _override_session_maker() -> async_sessionmaker:
    """Provide an in-memory SQLite session maker isolated from the main test DB."""
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


def _sep_proxies() -> dict:
    """Return the SEP-side proxy registry mirroring the lifespan wiring."""
    return {
        SettingClassEnum.SEP_SETTINGS: ProxyEntry(sep_settings, SEPSettings),
        SettingClassEnum.SNIPPETS_SETTINGS: ProxyEntry(
            snippets_settings, SnippetsSettings
        ),
        AlertsSettings.__name__: ProxyEntry(alerts_settings, AlertsSettings),
    }


@pytest.mark.asyncio
async def test_active_override_flips_value_after_refresh(
    override_session_maker: async_sessionmaker,
) -> None:
    """An active override row flips the value seen by the SEP proxy after refresh.

    The repository's ``settings.yaml`` ships ``CONNECTIVITY_CHECK_DEFAULT: false``,
    so we override to ``true`` to verify the override is observable irrespective
    of which value the operator defaulted to in YAML.
    """
    yaml_default = sep_settings.CONNECTIVITY_CHECK_DEFAULT
    override_value = not yaml_default
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is override_value


@pytest.mark.asyncio
async def test_restricted_deployment_filters_withheld_rows(
    override_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Assert a withheld key's row is filtered while an allowed one still lands."""
    endpoint_baseline = sep_settings.INVENTORY_ENDPOINT
    connectivity_override = not sep_settings.CONNECTIVITY_CHECK_DEFAULT
    monkeypatch.setattr(
        core_settings.SETTINGS_OVERRIDE,
        "ALLOWED_KEYS",
        {"SEPSettings.CONNECTIVITY_CHECK_DEFAULT"},
    )
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="INVENTORY_ENDPOINT",
                value="https://stale.example.com",
            ),
        )
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=connectivity_override,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert endpoint_baseline == sep_settings.INVENTORY_ENDPOINT
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is connectivity_override


@pytest.mark.asyncio
async def test_inactive_override_falls_back_to_yaml_default(
    override_session_maker: async_sessionmaker,
) -> None:
    """Deactivating the override row returns the proxy to the YAML default."""
    yaml_default = sep_settings.CONNECTIVITY_CHECK_DEFAULT
    override_value = not yaml_default
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is override_value

    async with override_session_maker() as session:
        await SettingsOverrideManager.update_where(
            session,
            {"is_active": False},
            setting_class=setting_class_token(SEPSettings),
            key="CONNECTIVITY_CHECK_DEFAULT",
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is yaml_default


@pytest.mark.asyncio
async def test_artifact_download_ttl_override_seen_at_validation_time(
    override_session_maker: async_sessionmaker,
) -> None:
    """The artifact-download TTL override is observable from the proxy.

    ``app/sep/routes/artifacts.py`` reads ``sep_settings.ARTIFACT_DOWNLOAD_TTL``
    at validation time inside the request handler; an override therefore
    affects every download token the next time validation runs.
    """
    override_ttl_seconds = 60
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="ARTIFACT_DOWNLOAD_TTL",
                value=override_ttl_seconds,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert override_ttl_seconds == sep_settings.ARTIFACT_DOWNLOAD_TTL


@pytest.mark.asyncio
async def test_snippets_enable_manual_sync_override(
    override_session_maker: async_sessionmaker,
) -> None:
    """The snippets ``ENABLE_MANUAL_SYNC`` flag is observable through the proxy."""
    yaml_default = snippets_settings.ENABLE_MANUAL_SYNC
    override_value = not yaml_default
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SnippetsSettings),
                key="ENABLE_MANUAL_SYNC",
                value=override_value,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert snippets_settings.ENABLE_MANUAL_SYNC is override_value


@pytest.mark.asyncio
async def test_per_class_isolation_prevents_key_leak(
    override_session_maker: async_sessionmaker,
) -> None:
    """A row for one class never bleeds into another class's snapshot.

    Insert a ``(SEP_SETTINGS, ENABLE_MANUAL_SYNC)`` row -- the key only exists
    on ``SnippetsSettings``. The cache must drop it as "unknown field" rather
    than apply it to the wrong class.
    """
    yaml_default = snippets_settings.ENABLE_MANUAL_SYNC
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="ENABLE_MANUAL_SYNC",
                value=not yaml_default,
            ),
        )
    await refresh_all(lambda: override_session_maker, _sep_proxies())
    assert snippets_settings.ENABLE_MANUAL_SYNC is yaml_default


@pytest.mark.asyncio
async def test_main_lifespan_starts_sep_overrides_refresher(
    override_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``main_lifespan`` runs the SEP override refresher at startup.

    ``sep_app`` is mounted under the top-level ``app`` via Starlette's
    ``Mount``, which only forwards ``http``/``websocket`` scopes -- never
    ``lifespan``. Therefore ``sep_lifespan`` is *never* invoked when
    ``python -m app.main`` runs uvicorn against ``app.main:app``. The
    ``SEP_SETTINGS``/``SNIPPETS_SETTINGS`` override
    refresher must therefore be wired into ``main_lifespan`` (analogous to
    how ``tasks_lifespan`` is wired). This test exercises that path: insert
    an override row, enter ``main_lifespan``, and assert the proxy sees the
    new value.
    """
    override_value = not sep_settings.CONNECTIVITY_CHECK_DEFAULT
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=override_value,
            ),
        )

    async def _no_op_sep_startup() -> None:
        """Stub ``sep_startup`` so the test does not hit the real SEP DB."""

    @asynccontextmanager
    async def _no_op_tasks_lifespan(_app):
        """Stub ``tasks_lifespan`` so the test does not hit the real tasks DB."""
        yield

    # Stub the SEP startup + tasks lifespan: this test focuses on the
    # override-refresher wiring, not the rest of the lifespan side effects.
    monkeypatch.setattr(main_module, "sep_startup", _no_op_sep_startup)
    monkeypatch.setattr(main_module, "tasks_lifespan", _no_op_tasks_lifespan)
    # Point the SEP session-maker factory at our in-memory override DB so the
    # refresher reads the row we just inserted instead of the real SEP DB.
    monkeypatch.setattr(
        "app.sep.main.get_async_session_maker", lambda: override_session_maker
    )
    # The session-scope autouse fixture in ``tests/app/conftest.py`` disables
    # the refresher for the whole test session; re-enable it here so this
    # test can exercise the real lifespan wiring.
    monkeypatch.setattr(core_settings.SETTINGS_OVERRIDE, "REFRESHER_ENABLED", True)

    fake_app = FastAPI()
    try:
        async with main_module.main_lifespan(fake_app):
            assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is override_value
    finally:
        # Restore the proxy snapshot so unrelated tests in the suite see
        # the YAML default again.
        sep_settings._set_snapshot({})
        snippets_settings._set_snapshot({})


@pytest_asyncio.fixture(name="beat_session_maker")
async def _beat_session_maker() -> async_sessionmaker:
    """Provide an in-memory SQLite session maker for the celery-beat schedule DB."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        json_serializer=json_serializer,
        poolclass=StaticPool,
    )
    engine = engine.execution_options(schema_translate_map={"celery_schema": None})
    async with engine.begin() as conn:
        await apply_schema(conn, PeriodicTask.__table__.metadata)
    try:
        yield get_async_session_maker_from_engine(engine)
    finally:
        await engine.dispose()


async def _seed_snippets_task(
    beat_session_maker: async_sessionmaker, *, every: int, enabled: bool
) -> None:
    """Seed a ``sep__sync_snippets`` beat row at the given interval/gating state."""
    from sqlalchemy_celery_beat.models import IntervalSchedule as BeatInterval
    from sqlalchemy_celery_beat.models import Period

    async with beat_session_maker() as session:
        schedule = BeatInterval(every=every, period=Period.HOURS)
        session.add(schedule)
        await session.flush()
        session.add(
            PeriodicTask(
                name=SNIPPETS_TASK,
                task="app.sep.snippets.celery.sync_snippets",
                enabled=enabled,
                schedule_model=schedule,
            )
        )
        await session.commit()


async def _seed_alert_backup_task(
    beat_session_maker: async_sessionmaker, *, every: int, enabled: bool
) -> None:
    """Seed a ``sep__backup_alert_config`` beat row at the given interval/gating."""
    from sqlalchemy_celery_beat.models import IntervalSchedule as BeatInterval
    from sqlalchemy_celery_beat.models import Period

    async with beat_session_maker() as session:
        schedule = BeatInterval(every=every, period=Period.HOURS)
        session.add(schedule)
        await session.flush()
        session.add(
            PeriodicTask(
                name=ALERT_BACKUP_TASK,
                task="app.sep.apps.alerts.celery.backup_alert_config",
                enabled=enabled,
                schedule_model=schedule,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_sync_interval_override_reseeds_beat_schedule_live(
    override_session_maker: async_sessionmaker,
    beat_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``SYNC_INTERVAL`` override re-seeds the live ``sep__sync_snippets`` beat row.

    Insert the override, run one refresh cycle with the SEP callbacks wired, and
    assert the beat-schedule row now carries the new interval. Beat applies it on
    its next scheduler tick (driven by the ``PeriodicTaskChanged.last_update``
    bump), not instantly -- this asserts the DB state the scheduler will reload,
    not in-process beat behavior.
    """
    # Gated OFF so we can prove the re-seed preserves the ``enabled`` flag.
    await _seed_snippets_task(beat_session_maker, every=1, enabled=False)
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SnippetsSettings),
                key="SYNC_INTERVAL",
                value={"every": OVERRIDE_EVERY_MINUTES, "period": "minutes"},
            ),
        )

    # ``init_periodic_tasks_db`` resolves its beat session via
    # ``app.core.celery.utils.get_async_session_maker`` -- point it at our beat DB.
    monkeypatch.setattr(
        "app.core.celery.utils.get_async_session_maker",
        lambda: beat_session_maker,
    )
    callbacks = {
        (
            SettingClassEnum.SNIPPETS_SETTINGS,
            "SYNC_INTERVAL",
        ): _reseed_system_periodic_tasks,
    }

    await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)

    # Proxy reflects the override...
    assert (
        IntervalSchedule(every=OVERRIDE_EVERY_MINUTES, period="minutes")
        == snippets_settings.SYNC_INTERVAL
    )
    # ...and the live beat row was re-seeded, gating state preserved.
    async with beat_session_maker() as session:
        task = await BasePeriodicTaskManager.first(session, name=SNIPPETS_TASK)
    assert task is not None
    from sqlalchemy_celery_beat.models import Period

    assert task.schedule_model.every == OVERRIDE_EVERY_MINUTES
    assert task.schedule_model.period == Period.MINUTES
    assert task.enabled is False  # gating survived the re-seed (AC #4)


@pytest.mark.asyncio
async def test_backup_interval_override_reseeds_alert_backup_beat_schedule_live(
    override_session_maker: async_sessionmaker,
    beat_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``BACKUP_INTERVAL`` override re-seeds the ``sep__backup_alert_config`` row.

    The alerts backup interval is a ``hot_field`` feeding the system beat schedule
    (:func:`app.sep.db.seed.get_system_periodic_tasks`). Wiring
    ``(AlertsSettings, BACKUP_INTERVAL)`` to ``_reseed_system_periodic_tasks`` means
    a runtime override updates the live beat row -- not just the proxy -- so Celery
    beat reloads it on its next tick without a restart. Mirrors the snippets case.
    """
    # The alerts schedule is plugin-gated on the app owning a Celery module; force
    # that lookup on irrespective of the test settings.yaml so the task-set builder
    # emits the alerts backup schedule.
    monkeypatch.setattr(
        "app.sep.db.seed.app_celery_module_for",
        lambda key, *_: "app.sep.apps.alerts.celery" if key == "alerts" else None,
    )
    # Gated OFF so we can prove the re-seed preserves the ``enabled`` flag.
    await _seed_alert_backup_task(beat_session_maker, every=1, enabled=False)
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class="ALERTS_SETTINGS",
                key="BACKUP_INTERVAL",
                value={"every": OVERRIDE_EVERY_MINUTES, "period": "minutes"},
            ),
        )

    monkeypatch.setattr(
        "app.core.celery.utils.get_async_session_maker",
        lambda: beat_session_maker,
    )
    callbacks = {
        (
            AlertsSettings.__name__,
            "BACKUP_INTERVAL",
        ): _reseed_system_periodic_tasks,
    }

    try:
        await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)

        # Proxy reflects the override...
        assert (
            IntervalSchedule(every=OVERRIDE_EVERY_MINUTES, period="minutes")
            == alerts_settings.BACKUP_INTERVAL
        )
        # ...and the live beat row was re-seeded, gating state preserved.
        async with beat_session_maker() as session:
            task = await BasePeriodicTaskManager.first(session, name=ALERT_BACKUP_TASK)
        assert task is not None
        from sqlalchemy_celery_beat.models import Period

        assert task.schedule_model.every == OVERRIDE_EVERY_MINUTES
        assert task.schedule_model.period == Period.MINUTES
        assert task.enabled is False  # gating survived the re-seed
    finally:
        # Restore the global proxy snapshot so unrelated tests see the YAML default.
        alerts_settings._set_snapshot({})


@pytest.mark.asyncio
async def test_invalid_sync_interval_override_keeps_default_and_skips_reseed(
    override_session_maker: async_sessionmaker,
    beat_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid override is logged+skipped: proxy keeps default, no re-seed fires.

    A non-positive ``every`` fails coercion in ``build_snapshot``; the snapshot is
    unchanged, so ``fire_change_callbacks`` never invokes the re-seed and the
    refresh cycle does not raise.
    """
    yaml_default = snippets_settings.SYNC_INTERVAL
    await _seed_snippets_task(beat_session_maker, every=1, enabled=True)
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SnippetsSettings),
                key="SYNC_INTERVAL",
                value={"every": 0, "period": "minutes"},
            ),
        )

    reseed_spy = AsyncMock()
    callbacks = {(SettingClassEnum.SNIPPETS_SETTINGS, "SYNC_INTERVAL"): reseed_spy}

    await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)

    assert yaml_default == snippets_settings.SYNC_INTERVAL
    reseed_spy.assert_not_awaited()
    # The beat row is untouched.
    async with beat_session_maker() as session:
        task = await BasePeriodicTaskManager.first(session, name=SNIPPETS_TASK)
    assert task.schedule_model.every == 1


@pytest.mark.asyncio
async def test_reseed_callback_failure_does_not_break_refresh_cycle(
    override_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing re-seed callback is isolated; other proxies still refresh.

    ``fire_change_callbacks`` wraps each callback in try/except, so a raising
    re-seed neither aborts the cycle nor blocks an unrelated override on a
    different proxy.
    """
    sep_override = not sep_settings.CONNECTIVITY_CHECK_DEFAULT
    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SnippetsSettings),
                key="SYNC_INTERVAL",
                value={"every": 30, "period": "minutes"},
            ),
        )
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SEPSettings),
                key="CONNECTIVITY_CHECK_DEFAULT",
                value=sep_override,
            ),
        )

    failing = AsyncMock(side_effect=RuntimeError("beat DB unreachable"))
    callbacks = {(SettingClassEnum.SNIPPETS_SETTINGS, "SYNC_INTERVAL"): failing}

    # Must not raise despite the callback blowing up.
    await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)

    failing.assert_awaited_once()
    # The unrelated SEP override still took effect.
    assert sep_settings.CONNECTIVITY_CHECK_DEFAULT is sep_override


async def _read_last_update(beat_session_maker: async_sessionmaker):
    """Return the singleton ``PeriodicTaskChanged.last_update``, or ``None``."""
    async with beat_session_maker() as session:
        result = await session.execute(select(PeriodicTaskChanged.last_update))
        return result.scalar_one_or_none()


async def _seed_reconciler_task(beat_session_maker: async_sessionmaker) -> None:
    """Seed the unrelated ``sep__reconcile_disabling_apps`` beat row.

    Uses the interval the builder reads for the reconciler
    (``sep_settings.APP_DRAIN.reconcile_interval``), so a re-seed's
    get-or-create resolves to this same schedule row and leaves the task
    untouched -- the precondition for the no-churn assertion.
    """
    from sqlalchemy_celery_beat.models import IntervalSchedule as BeatInterval

    interval = sep_settings.APP_DRAIN.reconcile_interval
    async with beat_session_maker() as session:
        schedule = BeatInterval(every=interval.every, period=interval.period)
        session.add(schedule)
        await session.flush()
        session.add(
            PeriodicTask(
                name=RECONCILER_TASK,
                task="app.sep.app_drain.reconcile_disabling_apps",
                enabled=True,
                schedule_model=schedule,
            )
        )
        await session.commit()


@pytest.mark.asyncio
async def test_reseed_bumps_periodic_task_changed_last_update(
    override_session_maker: async_sessionmaker,
    beat_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Re-seeding the snippets interval advances ``PeriodicTaskChanged.last_update``.

    AC #5: Celery beat reloads on the ``last_update`` bump written by the
    ``after_update`` listener when ``sep__sync_snippets``'s ``schedule_model`` is
    reassigned. The live-reseed test asserts the row's new value; this asserts
    the change-marker the running scheduler actually polls.
    """
    await _seed_snippets_task(beat_session_maker, every=1, enabled=True)
    before = await _read_last_update(beat_session_maker)

    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SnippetsSettings),
                key="SYNC_INTERVAL",
                value={"every": OVERRIDE_EVERY_MINUTES, "period": "minutes"},
            ),
        )
    monkeypatch.setattr(
        "app.core.celery.utils.get_async_session_maker",
        lambda: beat_session_maker,
    )
    callbacks = {
        (
            SettingClassEnum.SNIPPETS_SETTINGS,
            "SYNC_INTERVAL",
        ): _reseed_system_periodic_tasks,
    }
    try:
        await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)
    finally:
        snippets_settings._set_snapshot({})

    after = await _read_last_update(beat_session_maker)
    assert after is not None
    assert before is None or after > before


@pytest.mark.asyncio
async def test_reseed_does_not_churn_unrelated_task(
    override_session_maker: async_sessionmaker,
    beat_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A snippets-only override leaves the unrelated reconciler beat row untouched.

    Risk note: the callback re-runs ``init_periodic_tasks_db`` over the whole
    task set, not just the snippets entry. Its get-or-create + upsert path must
    not re-write a task whose schedule did not change, otherwise an unrelated
    ``after_update`` would needlessly churn the schedule. Pin the contract: the
    reconciler row's ``schedule_id`` (and interval) are unchanged after the
    re-seed, while the snippets row is updated.
    """
    await _seed_reconciler_task(beat_session_maker)
    await _seed_snippets_task(beat_session_maker, every=1, enabled=True)

    async with beat_session_maker() as session:
        reconciler_before = await BasePeriodicTaskManager.first(
            session, name=RECONCILER_TASK
        )
        reconciler_schedule_id_before = reconciler_before.schedule_id

    async with override_session_maker() as session:
        await SettingsOverrideManager.create(
            session,
            SettingOverride(
                setting_class=setting_class_token(SnippetsSettings),
                key="SYNC_INTERVAL",
                value={"every": OVERRIDE_EVERY_MINUTES, "period": "minutes"},
            ),
        )
    monkeypatch.setattr(
        "app.core.celery.utils.get_async_session_maker",
        lambda: beat_session_maker,
    )
    callbacks = {
        (
            SettingClassEnum.SNIPPETS_SETTINGS,
            "SYNC_INTERVAL",
        ): _reseed_system_periodic_tasks,
    }
    try:
        await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)
    finally:
        snippets_settings._set_snapshot({})

    from sqlalchemy_celery_beat.models import Period

    async with beat_session_maker() as session:
        reconciler_after = await BasePeriodicTaskManager.first(
            session, name=RECONCILER_TASK
        )
        snippets_after = await BasePeriodicTaskManager.first(
            session, name=SNIPPETS_TASK
        )
    # Unrelated task: schedule not churned.
    assert reconciler_after.schedule_id == reconciler_schedule_id_before
    assert (
        reconciler_after.schedule_model.every
        == sep_settings.APP_DRAIN.reconcile_interval.every
    )
    # Snippets task: did update.
    assert snippets_after.schedule_model.every == OVERRIDE_EVERY_MINUTES
    assert snippets_after.schedule_model.period == Period.MINUTES


@pytest.mark.asyncio
async def test_removing_sync_interval_override_reverts_beat_to_yaml_default(
    override_session_maker: async_sessionmaker,
    beat_session_maker: async_sessionmaker,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Deactivating the override reverts the beat row to the YAML default interval.

    Only the add path was covered. When the override is removed the proxy
    snapshot falls back to the ``settings.yaml`` default (``every=1`` hour); the
    snapshot change re-fires the callback, which re-seeds ``sep__sync_snippets``
    back to the default cadence.
    """
    from sqlalchemy_celery_beat.models import Period

    yaml_default = snippets_settings.SYNC_INTERVAL
    await _seed_snippets_task(beat_session_maker, every=1, enabled=True)
    monkeypatch.setattr(
        "app.core.celery.utils.get_async_session_maker",
        lambda: beat_session_maker,
    )
    callbacks = {
        (
            SettingClassEnum.SNIPPETS_SETTINGS,
            "SYNC_INTERVAL",
        ): _reseed_system_periodic_tasks,
    }

    try:
        # Override in, refresh -> beat row picks up the new cadence.
        async with override_session_maker() as session:
            await SettingsOverrideManager.create(
                session,
                SettingOverride(
                    setting_class=setting_class_token(SnippetsSettings),
                    key="SYNC_INTERVAL",
                    value={"every": OVERRIDE_EVERY_MINUTES, "period": "minutes"},
                ),
            )
        await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)
        async with beat_session_maker() as session:
            task = await BasePeriodicTaskManager.first(session, name=SNIPPETS_TASK)
        assert task.schedule_model.every == OVERRIDE_EVERY_MINUTES

        # Override out (deactivated), refresh -> beat row reverts to YAML default.
        async with override_session_maker() as session:
            await SettingsOverrideManager.update_where(
                session,
                {"is_active": False},
                setting_class=setting_class_token(SnippetsSettings),
                key="SYNC_INTERVAL",
            )
        await refresh_all(lambda: override_session_maker, _sep_proxies(), callbacks)
    finally:
        snippets_settings._set_snapshot({})

    assert yaml_default == snippets_settings.SYNC_INTERVAL
    async with beat_session_maker() as session:
        task = await BasePeriodicTaskManager.first(session, name=SNIPPETS_TASK)
    assert task.schedule_model.every == yaml_default.every
    assert task.schedule_model.period == Period(yaml_default.period)

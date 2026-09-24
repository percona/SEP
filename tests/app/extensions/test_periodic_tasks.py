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

"""Tests for the app-state periodic-task gating orchestrator."""

import json
import logging
from datetime import datetime

import pytest
from pytest_mock import MockerFixture
from sqlalchemy import delete, event
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask, PeriodicTaskChanged
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.utils import SystemPeriodicTaskData, SystemPeriodicTaskSchedule
from app.core.utils.date_time import utc_now
from app.extensions import periodic_tasks
from app.extensions.apps.framework.registry import AppRegistry
from app.extensions.apps.mysql_backups.forms import OWNER as BACKUPS_OWNER
from app.extensions.apps.mysql_backups.restore.models import OWNER as RESTORES_OWNER
from app.extensions.crud import ExtensionsAppPeriodicTaskManager
from app.extensions.models import AppLifecycleEnum, AppState, ExtensionsAppPeriodicTask
from app.extensions.periodic_tasks import (
    apply_effective_enabled,
    disable_schedules_for_owners,
    disable_unschedulable_task_schedules,
    release_unowned_task_gating,
    seed_app_periodic_task_rows,
)
from app.tasks.models import ANY_OWNER, Task
from tests.app.factories import TaskFactory

SNIPPETS_TASK = "extensions__sync_snippets"
ALERTS_TASK = "extensions__backup_alert_config"
SYSTEM_BEAT_TASK = "app.extensions.snippets.celery.sync_snippets"
USER_BEAT_TASK = "app.tasks.celery.execute_task_by_name"


async def _seed_periodic_task(
    session: AsyncSession,
    name: str,
    *,
    enabled: bool,
    every: int = 10,
    task: str = SYSTEM_BEAT_TASK,
    args: str = "[]",
    kwargs: str = "{}",
) -> PeriodicTask:
    """Create a celery-beat ``PeriodicTask`` row with its interval schedule."""
    schedule = IntervalSchedule(every=every, period=Period.MINUTES)
    session.add(schedule)
    await session.flush()
    periodic_task = PeriodicTask(
        name=name,
        task=task,
        enabled=enabled,
        args=args,
        kwargs=kwargs,
        schedule_model=schedule,
    )
    session.add(periodic_task)
    await session.commit()
    await session.refresh(periodic_task)
    return periodic_task


def _snippets_schedule() -> list[SystemPeriodicTaskSchedule]:
    """Build a one-entry system-task list owning the snippets schedule."""
    return [
        SystemPeriodicTaskSchedule(
            schedule=IntervalSchedule(every=10, period=Period.MINUTES),
            tasks=[
                SystemPeriodicTaskData(
                    name=SNIPPETS_TASK,
                    task_name="app.extensions.snippets.celery.sync_snippets",
                    owner_app_key="snippets",
                ),
            ],
        ),
    ]


@pytest.mark.asyncio
class TestSeedAppPeriodicTaskRows:
    """Tests for :func:`app.extensions.periodic_tasks.seed_app_periodic_task_rows`."""

    async def test_upserts_one_row_per_owned_task(self, session: AsyncSession) -> None:
        """Each owned schedule yields a wrapper row defaulting to ``user_enabled``."""
        await seed_app_periodic_task_rows(session, _snippets_schedule())

        rows = await ExtensionsAppPeriodicTaskManager.list(session)
        assert {r.periodic_task_name for r in rows} == {SNIPPETS_TASK}
        assert rows[0].app_key == "snippets"
        assert rows[0].user_enabled is True

    async def test_templated_tasks_each_get_a_row_under_one_owner(
        self, session: AsyncSession
    ) -> None:
        """Every templated schedule of one app (e.g. health-report) gets its own row."""
        system_tasks = [
            SystemPeriodicTaskSchedule(
                schedule=IntervalSchedule(every=10, period=Period.MINUTES),
                tasks=[
                    SystemPeriodicTaskData(
                        name="extensions__generate_health_report",
                        task_name="app.extensions.apps.report.celery.generate_health_report",
                        owner_app_key="report",
                    ),
                    SystemPeriodicTaskData(
                        name="extensions__generate_health_report_1",
                        task_name="app.extensions.apps.report.celery.generate_health_report",
                        owner_app_key="report",
                    ),
                ],
            ),
        ]

        await seed_app_periodic_task_rows(session, system_tasks)

        rows = await ExtensionsAppPeriodicTaskManager.list(session)
        assert {r.periodic_task_name for r in rows} == {
            "extensions__generate_health_report",
            "extensions__generate_health_report_1",
        }
        assert {r.app_key for r in rows} == {"report"}

    async def test_existing_user_enabled_not_overwritten(
        self, session: AsyncSession
    ) -> None:
        """A user-set ``user_enabled=False`` survives a re-seed."""
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=False
            )
        )
        await session.commit()

        await seed_app_periodic_task_rows(session, _snippets_schedule())

        row = await ExtensionsAppPeriodicTaskManager.first(
            session, periodic_task_name=SNIPPETS_TASK
        )
        assert row.user_enabled is False

    async def test_orphan_rows_deleted(self, session: AsyncSession) -> None:
        """Wrapper rows for no-longer-owned tasks are removed."""
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name="extensions__ghost",
                app_key="ghost",
                user_enabled=True,
            )
        )
        await session.commit()

        await seed_app_periodic_task_rows(session, _snippets_schedule())

        rows = await ExtensionsAppPeriodicTaskManager.list(session)
        assert {r.periodic_task_name for r in rows} == {SNIPPETS_TASK}


@pytest.mark.asyncio
class TestApplyEffectiveEnabled:
    """Tests for :func:`app.extensions.periodic_tasks.apply_effective_enabled`."""

    @pytest.mark.parametrize(
        "state",
        [
            AppLifecycleEnum.DISABLED,
            AppLifecycleEnum.DISABLING,
            AppLifecycleEnum.ENABLING,
        ],
    )
    async def test_non_enabled_app_disables_owned_task(
        self, session: AsyncSession, celery_beat_session: AsyncSession, state
    ) -> None:
        """Any non-``ENABLED`` app flips its owned ``PeriodicTask.enabled`` off."""
        session.add(AppState(app_key="snippets", lifecycle_state=state))
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)

        await apply_effective_enabled(session, celery_beat_session)

        task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        assert task.enabled is False

    async def test_user_disabled_stays_off_when_app_enabled(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """``user_enabled=False`` keeps a schedule off even when the app is on."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=False
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)

        await apply_effective_enabled(session, celery_beat_session)

        task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        assert task.enabled is False

    async def test_enabled_app_and_user_enables_task(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """An enabled app + ``user_enabled`` re-enables a previously-off schedule."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=False)

        await apply_effective_enabled(session, celery_beat_session)

        task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        assert task.enabled is True

    async def test_missing_app_state_treated_as_enabled(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """A missing ``AppState`` row is treated as enabled (mirrors ``is_enabled``)."""
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=False)

        await apply_effective_enabled(session, celery_beat_session)

        task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        assert task.enabled is True

    async def test_missing_periodic_task_is_noop(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """A wrapper row with no matching ``PeriodicTask`` is skipped without error."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        await session.commit()

        await apply_effective_enabled(session, celery_beat_session)

        assert (
            await BasePeriodicTaskManager.first(celery_beat_session, name=SNIPPETS_TASK)
            is None
        )

    async def test_no_wrapper_rows_returns_early(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """With no wrapper rows the call returns without touching the beat DB."""
        await apply_effective_enabled(session, celery_beat_session)

    async def test_unchanged_state_skips_write(
        self, session: AsyncSession, celery_beat_session: AsyncSession, mocker
    ) -> None:
        """Skip the write (and beat reload) when the effective value is unchanged."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)

        add_spy = mocker.spy(celery_beat_session, "add")
        commit_spy = mocker.spy(celery_beat_session, "commit")
        await apply_effective_enabled(session, celery_beat_session)
        add_spy.assert_not_called()
        commit_spy.assert_not_called()

    async def test_app_keys_filter_limits_scope(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """``app_keys`` restricts the sweep to the named apps' owned tasks."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        session.add(
            AppState(app_key="alerts", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=ALERTS_TASK, app_key="alerts", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)
        await _seed_periodic_task(
            celery_beat_session, ALERTS_TASK, enabled=True, every=20
        )

        await apply_effective_enabled(
            session, celery_beat_session, app_keys={"snippets"}
        )

        snippets = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        alerts = await BasePeriodicTaskManager.first(
            celery_beat_session, name=ALERTS_TASK
        )
        assert snippets.enabled is False
        assert alerts.enabled is True

    async def test_unfiltered_sweep_gates_every_owned_row(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """An unfiltered sweep recomputes every owned task's enabled bit."""
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        session.add(
            AppState(app_key="alerts", lifecycle_state=AppLifecycleEnum.ENABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=ALERTS_TASK, app_key="alerts", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)
        await _seed_periodic_task(
            celery_beat_session, ALERTS_TASK, enabled=False, every=20
        )

        await apply_effective_enabled(session, celery_beat_session)

        snippets = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        alerts = await BasePeriodicTaskManager.first(
            celery_beat_session, name=ALERTS_TASK
        )
        assert snippets.enabled is False
        assert alerts.enabled is True

    async def test_beat_commit_failure_propagates(
        self, session: AsyncSession, celery_beat_session: AsyncSession, mocker
    ) -> None:
        """A failed beat-DB commit surfaces as an error rather than silent drift.

        ``AppState`` is committed by its own manager before this runs, so a beat
        commit failure leaves a bounded, self-healing inconsistency the next
        startup sweep (or a re-toggle) reconciles — the caller sees the error and
        does not assume the gate took effect.
        """
        session.add(
            AppState(app_key="snippets", lifecycle_state=AppLifecycleEnum.DISABLED)
        )
        session.add(
            ExtensionsAppPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        await session.commit()
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)
        mocker.patch.object(
            celery_beat_session, "commit", side_effect=RuntimeError("beat down")
        )

        with pytest.raises(RuntimeError, match="beat down"):
            await apply_effective_enabled(session, celery_beat_session)


@pytest.mark.asyncio
class TestReleaseUnownedTaskGating:
    """Cover :func:`app.extensions.periodic_tasks.release_unowned_task_gating`."""

    @staticmethod
    def _unowned_schedule() -> list[SystemPeriodicTaskSchedule]:
        """Build a one-entry system-task list carrying no ``owner_app_key``."""
        return [
            SystemPeriodicTaskSchedule(
                schedule=IntervalSchedule(every=10, period=Period.MINUTES),
                tasks=[
                    SystemPeriodicTaskData(
                        name=SNIPPETS_TASK,
                        task_name="app.extensions.snippets.celery.sync_snippets",
                    ),
                ],
            ),
        ]

    async def test_stale_disable_is_released(
        self, celery_beat_session: AsyncSession
    ) -> None:
        """Enable an unowned schedule's beat row when a past gate left it off."""
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=False)

        await release_unowned_task_gating(celery_beat_session, self._unowned_schedule())

        task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=SNIPPETS_TASK
        )
        assert task.enabled is True

    async def test_owned_schedule_is_left_alone(
        self, celery_beat_session: AsyncSession
    ) -> None:
        """Leave an owned schedule to ``apply_effective_enabled`` rather than forcing it."""
        await _seed_periodic_task(celery_beat_session, ALERTS_TASK, enabled=False)
        owned = [
            SystemPeriodicTaskSchedule(
                schedule=IntervalSchedule(every=10, period=Period.MINUTES),
                tasks=[
                    SystemPeriodicTaskData(
                        name=ALERTS_TASK,
                        task_name="app.extensions.apps.alerts.celery.backup_alert_config",
                        owner_app_key="alerts",
                    ),
                ],
            ),
        ]

        await release_unowned_task_gating(celery_beat_session, owned)

        task = await BasePeriodicTaskManager.first(
            celery_beat_session, name=ALERTS_TASK
        )
        assert task.enabled is False

    async def test_already_enabled_row_skips_the_write(
        self, celery_beat_session: AsyncSession, mocker
    ) -> None:
        """Skip the commit (and the beat reload it signals) when nothing changes."""
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)
        commit_spy = mocker.spy(celery_beat_session, "commit")

        await release_unowned_task_gating(celery_beat_session, self._unowned_schedule())

        commit_spy.assert_not_called()


async def _seed_task(
    session: AsyncSession, name: str, owner: str, *, deleted_at: datetime | None = None
) -> Task:
    """Persist a Tasks-database ``Task`` row under ``owner``."""
    task = TaskFactory.build(name=name, owner=owner, deleted_at=deleted_at)
    session.add(task)
    await session.commit()
    return task


async def _seed_user_schedule(
    session: AsyncSession,
    name: str,
    *,
    enabled: bool = True,
    args: str = "[]",
    kwargs: str = "{}",
) -> PeriodicTask:
    """Seed a user schedule the Tasks service would have written."""
    return await _seed_periodic_task(
        session,
        name,
        enabled=enabled,
        task=USER_BEAT_TASK,
        args=args,
        kwargs=kwargs,
    )


async def _clear_changed_marker(session: AsyncSession) -> None:
    """Drop the beat reload marker so a later read proves the sweep rewrote it."""
    await session.execute(delete(PeriodicTaskChanged))  # ty: ignore[deprecated]
    await session.commit()


async def _read_enabled(session: AsyncSession, name: str) -> bool:
    """Return the current ``enabled`` bit of the schedule named ``name``."""
    session.expire_all()
    row = await BasePeriodicTaskManager.first(session, name=name)
    assert row is not None, f"no schedule named {name!r}"
    return row.enabled


def _sweep_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the sweep's own WARNING messages, ignoring the beat library's logs."""
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == periodic_tasks.__name__ and record.levelno == logging.WARNING
    ]


@pytest.mark.asyncio
class TestDisableSchedulesForOwners:
    """Cover the startup sweep that switches off unschedulable owners' schedules."""

    async def test_restore_schedule_is_switched_off(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Disable an enabled restore schedule and signal the beat reload."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )
        await _clear_changed_marker(celery_beat_session)

        with caplog.at_level(logging.WARNING):
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )

        assert switched_off == ["nightly-restore"]
        assert await _read_enabled(celery_beat_session, "nightly-restore") is False
        assert [m for m in _sweep_warnings(caplog) if "nightly-restore" in m]
        result = await celery_beat_session.exec(select(PeriodicTaskChanged.last_update))
        assert result.one_or_none() is not None

    async def test_schedule_beyond_first_batch_is_switched_off(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        mocker: MockerFixture,
    ) -> None:
        """Continue scanning schedules after a batch with no matching row."""
        mocker.patch.object(periodic_tasks, "SCHEDULE_BATCH_SIZE", 1)
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "unrelated",
            kwargs=json.dumps({"task_name": "other"}),
        )
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )

        switched_off = await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        assert switched_off == ["nightly-restore"]
        assert await _read_enabled(celery_beat_session, "nightly-restore") is False

    async def test_task_beyond_first_batch_is_matched(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        mocker: MockerFixture,
    ) -> None:
        """Match a schedule whose owned task lands beyond the first task batch."""
        mocker.patch.object(periodic_tasks, "ACTIVE_TASK_BATCH_SIZE", 1)
        await _seed_task(session, "r0", RESTORES_OWNER)
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )

        switched_off = await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        assert switched_off == ["nightly-restore"]
        assert await _read_enabled(celery_beat_session, "nightly-restore") is False

    async def test_task_scan_does_not_fetch_the_task_payload(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        mocker: MockerFixture,
    ) -> None:
        """Keep ``Task.data`` out of every task-batch query, not just unread.

        Schedules are matched by task name alone, so a scan that loaded whole rows
        would pass every behavioural assertion here while still transferring each
        task's payload at startup.
        """
        mocker.patch.object(periodic_tasks, "ACTIVE_TASK_BATCH_SIZE", 1)
        await _seed_task(session, "r0", RESTORES_OWNER)
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )
        statements: list[str] = []

        def _record(
            conn: object, cursor: object, statement: str, *args: object
        ) -> None:
            statements.append(statement)

        bind = session.get_bind()
        event.listen(bind, "before_cursor_execute", _record)
        try:
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )
        finally:
            event.remove(bind, "before_cursor_execute", _record)

        assert switched_off == ["nightly-restore"]
        task_selects = [s for s in statements if "FROM task" in s]
        assert len(task_selects) > 1, "the task scan did not page past one batch"
        assert not any("task.data" in s for s in task_selects)

    async def test_other_owners_and_system_rows_are_untouched(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """Leave backup, ``ANY_OWNER`` and system schedules enabled."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_task(session, "b1", BACKUPS_OWNER)
        await _seed_task(session, "inventory-sync", ANY_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-backup",
            kwargs=json.dumps({"task_name": "b1"}),
        )
        await _seed_user_schedule(
            celery_beat_session,
            "inventory-sync-schedule",
            kwargs=json.dumps({"task_name": "inventory-sync"}),
        )
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)

        await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        assert await _read_enabled(celery_beat_session, "nightly-restore") is False
        assert await _read_enabled(celery_beat_session, "nightly-backup") is True
        assert (
            await _read_enabled(celery_beat_session, "inventory-sync-schedule") is True
        )
        assert await _read_enabled(celery_beat_session, SNIPPETS_TASK) is True

    async def test_rows_running_another_celery_callable_are_never_examined(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Ignore a beat row whose callable is not the task-execution entry point.

        ``PeriodicTaskManager`` pins ``task`` to ``execute_task_by_name``, so a row
        running anything else is never enumerated — not switched off even when its
        arguments name an unschedulable task, and not warned about when it carries
        no task name at all.
        """
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_periodic_task(
            celery_beat_session,
            "impostor",
            enabled=True,
            task=SYSTEM_BEAT_TASK,
            kwargs=json.dumps({"task_name": "r1"}),
        )
        await _seed_periodic_task(celery_beat_session, SNIPPETS_TASK, enabled=True)

        with caplog.at_level(logging.WARNING):
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )

        assert switched_off == []
        assert await _read_enabled(celery_beat_session, "impostor") is True
        assert await _read_enabled(celery_beat_session, SNIPPETS_TASK) is True
        assert _sweep_warnings(caplog) == []

    async def test_second_run_is_a_no_op(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Leave every row as it stands on a second startup: only enabled ones match."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )
        await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        with caplog.at_level(logging.WARNING):
            caplog.clear()
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )

        assert switched_off == []
        assert _sweep_warnings(caplog) == []

    async def test_already_disabled_schedule_is_left_alone(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Skip a restore schedule an operator already switched off."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            enabled=False,
            kwargs=json.dumps({"task_name": "r1"}),
        )

        with caplog.at_level(logging.WARNING):
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )

        assert switched_off == []
        assert _sweep_warnings(caplog) == []

    async def test_soft_deleted_task_is_not_matched(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """Leave a schedule alone when its restore task is soft-deleted."""
        await _seed_task(session, "r1", RESTORES_OWNER, deleted_at=utc_now())
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )

        switched_off = await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        assert switched_off == []
        assert await _read_enabled(celery_beat_session, "nightly-restore") is True

    async def test_positional_args_encoding_is_resolved(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """Cover a pre-existing row that names its task positionally in ``args``."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session, "legacy-restore", args=json.dumps(["r1"]), kwargs="{}"
        )

        switched_off = await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        assert switched_off == ["legacy-restore"]

    async def test_kwargs_task_name_overrides_positional_args(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """Resolve to ``kwargs.task_name``, as the Tasks model does."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_task(session, "b1", BACKUPS_OWNER)
        await _seed_user_schedule(
            celery_beat_session,
            "repointed",
            args=json.dumps(["r1"]),
            kwargs=json.dumps({"task_name": "b1"}),
        )

        switched_off = await disable_schedules_for_owners(
            session, celery_beat_session, [RESTORES_OWNER]
        )

        assert switched_off == []
        assert await _read_enabled(celery_beat_session, "repointed") is True

    async def test_malformed_row_is_skipped_with_a_warning(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Skip a row whose arguments will not parse without stopping the sweep."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(celery_beat_session, "corrupt", kwargs="{not json")
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )

        with caplog.at_level(logging.WARNING):
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )

        assert switched_off == ["nightly-restore"]
        assert await _read_enabled(celery_beat_session, "corrupt") is True
        assert [m for m in _sweep_warnings(caplog) if "corrupt" in m]

    async def test_wrong_shape_arguments_are_skipped_with_a_warning(
        self,
        session: AsyncSession,
        celery_beat_session: AsyncSession,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Skip a row whose ``kwargs`` parses to the wrong JSON shape."""
        await _seed_task(session, "r1", RESTORES_OWNER)
        await _seed_user_schedule(
            celery_beat_session, "list-kwargs", kwargs=json.dumps(["r1"])
        )
        await _seed_user_schedule(
            celery_beat_session,
            "nightly-restore",
            kwargs=json.dumps({"task_name": "r1"}),
        )

        with caplog.at_level(logging.WARNING):
            switched_off = await disable_schedules_for_owners(
                session, celery_beat_session, [RESTORES_OWNER]
            )

        assert switched_off == ["nightly-restore"]
        assert await _read_enabled(celery_beat_session, "list-kwargs") is True
        assert [m for m in _sweep_warnings(caplog) if "list-kwargs" in m]

    async def test_no_owners_returns_an_empty_list(
        self, session: AsyncSession, celery_beat_session: AsyncSession
    ) -> None:
        """Return an empty list when the caller supplies no owners."""
        assert (
            await disable_schedules_for_owners(session, celery_beat_session, []) == []
        )


@pytest.mark.asyncio
class TestDisableUnschedulableTaskSchedules:
    """Cover the startup entry point that resolves the owners from the registry."""

    async def test_no_unschedulable_owner_opens_no_session(
        self, mocker: MockerFixture
    ) -> None:
        """Skip both databases when every registered task app offers scheduling."""
        mocker.patch.object(
            periodic_tasks,
            "get_app_registry",
            return_value=AppRegistry([]),
        )
        tasks_maker = mocker.patch.object(
            periodic_tasks, "get_tasks_session_maker", side_effect=AssertionError
        )
        beat_maker = mocker.patch.object(
            periodic_tasks, "get_celery_beat_session_maker", side_effect=AssertionError
        )

        await disable_unschedulable_task_schedules()

        tasks_maker.assert_not_called()
        beat_maker.assert_not_called()

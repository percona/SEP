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

import pytest
from sqlalchemy_celery_beat import IntervalSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.utils import SystemPeriodicTaskData, SystemPeriodicTaskSchedule
from app.sep.crud import SEPPluginPeriodicTaskManager
from app.sep.models import AppLifecycleEnum, AppState, SEPPluginPeriodicTask
from app.sep.periodic_tasks import apply_effective_enabled, seed_app_periodic_task_rows

SNIPPETS_TASK = "sep__sync_snippets"
ALERTS_TASK = "sep__backup_alert_config"


async def _seed_periodic_task(
    session: AsyncSession, name: str, *, enabled: bool, every: int = 10
) -> PeriodicTask:
    """Create a celery-beat ``PeriodicTask`` row with its interval schedule."""
    schedule = IntervalSchedule(every=every, period=Period.MINUTES)
    session.add(schedule)
    await session.flush()
    task = PeriodicTask(
        name=name,
        task="app.sep.celery.sync_snippets",
        enabled=enabled,
        schedule_model=schedule,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


def _snippets_schedule() -> list[SystemPeriodicTaskSchedule]:
    """Build a one-entry system-task list owning the snippets schedule."""
    return [
        SystemPeriodicTaskSchedule(
            schedule=IntervalSchedule(every=10, period=Period.MINUTES),
            tasks=[
                SystemPeriodicTaskData(
                    name=SNIPPETS_TASK,
                    task_name="app.sep.celery.sync_snippets",
                    owner_app_key="snippets",
                ),
            ],
        ),
    ]


@pytest.mark.asyncio
class TestSeedAppPeriodicTaskRows:
    """Tests for :func:`app.sep.periodic_tasks.seed_app_periodic_task_rows`."""

    async def test_upserts_one_row_per_owned_task(self, session: AsyncSession) -> None:
        """Each owned schedule yields a wrapper row defaulting to ``user_enabled``."""
        await seed_app_periodic_task_rows(session, _snippets_schedule())

        rows = await SEPPluginPeriodicTaskManager.list(session)
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
                        name="sep__generate_health_report",
                        task_name="app.sep.apps.report.celery.generate_health_report",
                        owner_app_key="report",
                    ),
                    SystemPeriodicTaskData(
                        name="sep__generate_health_report_1",
                        task_name="app.sep.apps.report.celery.generate_health_report",
                        owner_app_key="report",
                    ),
                ],
            ),
        ]

        await seed_app_periodic_task_rows(session, system_tasks)

        rows = await SEPPluginPeriodicTaskManager.list(session)
        assert {r.periodic_task_name for r in rows} == {
            "sep__generate_health_report",
            "sep__generate_health_report_1",
        }
        assert {r.app_key for r in rows} == {"report"}

    async def test_existing_user_enabled_not_overwritten(
        self, session: AsyncSession
    ) -> None:
        """A user-set ``user_enabled=False`` survives a re-seed."""
        session.add(
            SEPPluginPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=False
            )
        )
        await session.commit()

        await seed_app_periodic_task_rows(session, _snippets_schedule())

        row = await SEPPluginPeriodicTaskManager.first(
            session, periodic_task_name=SNIPPETS_TASK
        )
        assert row.user_enabled is False

    async def test_orphan_rows_deleted(self, session: AsyncSession) -> None:
        """Wrapper rows for no-longer-owned tasks are removed."""
        session.add(
            SEPPluginPeriodicTask(
                periodic_task_name="sep__ghost", app_key="ghost", user_enabled=True
            )
        )
        await session.commit()

        await seed_app_periodic_task_rows(session, _snippets_schedule())

        rows = await SEPPluginPeriodicTaskManager.list(session)
        assert {r.periodic_task_name for r in rows} == {SNIPPETS_TASK}


@pytest.mark.asyncio
class TestApplyEffectiveEnabled:
    """Tests for :func:`app.sep.periodic_tasks.apply_effective_enabled`."""

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
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        session.add(
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
                periodic_task_name=SNIPPETS_TASK, app_key="snippets", user_enabled=True
            )
        )
        session.add(
            SEPPluginPeriodicTask(
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
            SEPPluginPeriodicTask(
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

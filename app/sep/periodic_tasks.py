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

"""Gate plugin-owned Celery periodic tasks by app state.

A schedule's ``effective_enabled`` is
``(AppState.lifecycle_state == ENABLED) AND user_enabled``. This
module recomputes it for plugin-owned tasks and writes it through to the library
``sqlalchemy_celery_beat.PeriodicTask.enabled`` column, the single field the beat
scheduler filters on. The write is an ORM-instance mutation, so the library's
``after_update`` listener bumps ``PeriodicTaskChanged.last_update`` and the
running scheduler reloads without a restart.

The work spans two databases — ``AppState`` and the wrapper rows live in the SEP
database, while ``PeriodicTask`` lives in the celery-beat database — so it cannot
ride on a single manager ``save()``. It is instead invoked from the two
enumerated writers of ``AppState.lifecycle_state``: startup seeding
(:func:`app.sep.db.seed.init_sep_db`) and the runtime toggle endpoint.
"""

from collections.abc import Collection

from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.db import get_async_session_maker as get_celery_beat_session_maker
from app.core.celery.utils import SystemPeriodicTaskSchedule
from app.sep.crud import AppStateManager, SEPPluginPeriodicTaskManager
from app.sep.db import get_async_session_maker as get_sep_session_maker
from app.sep.models import (
    AppLifecycleEnum,
    SEPPluginPeriodicTask,
    SEPPluginPeriodicTaskBase,
)


async def seed_app_periodic_task_rows(
    session: AsyncSession, system_tasks: list[SystemPeriodicTaskSchedule]
) -> None:
    """Upsert one wrapper row per plugin-owned schedule and delete orphans.

    Idempotent: ``get_or_create`` never overwrites an operator-set
    ``user_enabled``, so a disabled-by-the-user schedule stays disabled across
    restarts.

    :param session: The SEP database session.
    :param system_tasks: The system periodic-task schedules to seed from.
    """
    owned = [
        task
        for schedule in system_tasks
        for task in schedule.tasks
        if task.owner_app_key
    ]
    for task in owned:
        await SEPPluginPeriodicTaskManager.get_or_create(
            session,
            SEPPluginPeriodicTaskBase(
                periodic_task_name=task.name, app_key=task.owner_app_key
            ),
            filter_include={"periodic_task_name"},
        )
    owned_names = [task.name for task in owned]
    await SEPPluginPeriodicTaskManager.delete_where(
        session, col(SEPPluginPeriodicTask.periodic_task_name).not_in(owned_names)
    )


async def apply_effective_enabled(
    sep_session: AsyncSession,
    celery_beat_session: AsyncSession,
    *,
    app_keys: Collection[str] | None = None,
) -> None:
    """Recompute ``effective_enabled`` and write it to ``PeriodicTask.enabled``.

    ``effective_enabled`` is
    ``(AppState.lifecycle_state == ENABLED) AND user_enabled``. A missing
    ``AppState`` row is treated as enabled, mirroring
    :meth:`app.sep.crud.AppStateManager.is_enabled`. The write is an ORM-instance
    mutation guarded by an equality check, so the library reload signal only
    fires when a value actually changes.

    :param sep_session: The SEP database session (``AppState`` + wrapper rows).
    :param celery_beat_session: The celery-beat database session (``PeriodicTask``).
    :param app_keys: Restrict the sweep to these app keys, or ``None`` for all.
    """
    rows = await SEPPluginPeriodicTaskManager.for_app_keys(sep_session, app_keys)
    if not rows:
        return
    lifecycle_state = await AppStateManager.all_lifecycle_states(sep_session)
    tasks = await BasePeriodicTaskManager.list(
        celery_beat_session,
        PeriodicTask.name.in_([row.periodic_task_name for row in rows]),
    )
    tasks_by_name = {task.name: task for task in tasks}
    changed = False
    for row in rows:
        task = tasks_by_name.get(row.periodic_task_name)
        if task is None:
            continue
        effective = (
            lifecycle_state.get(row.app_key, AppLifecycleEnum.ENABLED)
            == AppLifecycleEnum.ENABLED
        ) and row.user_enabled
        if task.enabled != effective:
            task.enabled = effective
            celery_beat_session.add(task)
            changed = True
    if changed:
        await celery_beat_session.commit()


async def release_unowned_task_gating(
    celery_beat_session: AsyncSession,
    system_tasks: list[SystemPeriodicTaskSchedule],
) -> None:
    """Enable seeded ``PeriodicTask`` rows for schedules that carry no owner.

    An unowned schedule gets no ``SEPPluginPeriodicTask`` wrapper row, so it has
    no user toggle and ``enabled`` is a column only app gating ever writes.
    :func:`apply_effective_enabled` iterates wrapper rows, which means a schedule
    that *loses* its owner keeps whatever bit the previous regime left behind and
    nothing ever writes it back — permanently off on an instance whose former
    owning app was disabled at the time. Re-assert the only correct value for a
    schedule nothing gates.

    :param celery_beat_session: The celery-beat database session.
    :param system_tasks: The system periodic-task schedules to seed from.
    """
    unowned = [
        task.name
        for schedule in system_tasks
        for task in schedule.tasks
        if not task.owner_app_key
    ]
    if not unowned:
        return
    tasks = await BasePeriodicTaskManager.list(
        celery_beat_session, col(PeriodicTask.name).in_(unowned)
    )
    changed = False
    for task in tasks:
        if not task.enabled:
            task.enabled = True
            celery_beat_session.add(task)
            changed = True
    if changed:
        await celery_beat_session.commit()


async def sync_app_periodic_task_gating(
    system_tasks: list[SystemPeriodicTaskSchedule],
) -> None:
    """Seed wrapper rows and apply ``effective_enabled`` for every owned task.

    Startup entry point: opens one SEP session and one celery-beat session,
    upserts the wrapper rows, releases any schedule that no longer has an owner,
    then writes ``effective_enabled`` through for all owned schedules.

    :param system_tasks: The system periodic-task schedules to gate.
    """
    sep_session_maker = get_sep_session_maker()
    celery_beat_session_maker = get_celery_beat_session_maker()
    async with (
        sep_session_maker() as sep_session,
        celery_beat_session_maker() as celery_beat_session,
    ):
        await seed_app_periodic_task_rows(sep_session, system_tasks)
        await release_unowned_task_gating(celery_beat_session, system_tasks)
        await apply_effective_enabled(sep_session, celery_beat_session)

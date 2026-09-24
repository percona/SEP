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

The work spans two databases — ``AppState`` and the wrapper rows live in the PMM Extensions
database, while ``PeriodicTask`` lives in the celery-beat database — so it cannot
ride on a single manager ``save()``. It is instead invoked from the two
enumerated writers of ``AppState.lifecycle_state``: startup seeding
(:func:`app.extensions.db.seed.init_extensions_db`) and the runtime toggle endpoint.

The module carries a second, narrower concern with the same shape: a *user*
schedule whose task belongs to an app that does not offer scheduling at all. Such
a schedule predates the app withdrawing the capability, and the gateway guard only
refuses new writes, so :func:`disable_unschedulable_task_schedules` switches the
stored ones off once per PMM Extensions startup. It reads a third database — the Tasks one,
which owns the ``Task.owner`` those schedules resolve against.
"""

import logging
from collections.abc import Collection

from sqlalchemy.orm import load_only
from sqlalchemy_celery_beat import PeriodicTask
from sqlmodel import col
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.celery.crud import BasePeriodicTaskManager
from app.core.celery.db import get_async_session_maker as get_celery_beat_session_maker
from app.core.celery.utils import SystemPeriodicTaskSchedule
from app.extensions.apps.framework.registry import get_app_registry
from app.extensions.crud import AppStateManager, ExtensionsAppPeriodicTaskManager
from app.extensions.db import get_async_session_maker as get_extensions_session_maker
from app.extensions.models import (
    AppLifecycleEnum,
    ExtensionsAppPeriodicTask,
    ExtensionsAppPeriodicTaskBase,
)
from app.tasks.crud import ACTIVE_TASK_BATCH_SIZE, TaskManager
from app.tasks.db import get_async_session_maker as get_tasks_session_maker
from app.tasks.models import Task
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.utils import resolve_schedule_task_name

logger = logging.getLogger(__name__)

SCHEDULE_BATCH_SIZE = 500


async def seed_app_periodic_task_rows(
    session: AsyncSession, system_tasks: list[SystemPeriodicTaskSchedule]
) -> None:
    """Upsert one wrapper row per plugin-owned schedule and delete orphans.

    Idempotent: ``get_or_create`` never overwrites an operator-set
    ``user_enabled``, so a disabled-by-the-user schedule stays disabled across
    restarts.

    :param session: The PMM Extensions database session.
    :param system_tasks: The system periodic-task schedules to seed from.
    """
    owned = [
        task
        for schedule in system_tasks
        for task in schedule.tasks
        if task.owner_app_key
    ]
    for task in owned:
        await ExtensionsAppPeriodicTaskManager.get_or_create(
            session,
            ExtensionsAppPeriodicTaskBase(
                periodic_task_name=task.name, app_key=task.owner_app_key
            ),
            filter_include={"periodic_task_name"},
        )
    owned_names = [task.name for task in owned]
    await ExtensionsAppPeriodicTaskManager.delete_where(
        session, col(ExtensionsAppPeriodicTask.periodic_task_name).not_in(owned_names)
    )


async def apply_effective_enabled(
    extensions_session: AsyncSession,
    celery_beat_session: AsyncSession,
    *,
    app_keys: Collection[str] | None = None,
) -> None:
    """Recompute ``effective_enabled`` and write it to ``PeriodicTask.enabled``.

    ``effective_enabled`` is
    ``(AppState.lifecycle_state == ENABLED) AND user_enabled``. A missing
    ``AppState`` row is treated as enabled, mirroring
    :meth:`app.extensions.crud.AppStateManager.is_enabled`. The write is an ORM-instance
    mutation guarded by an equality check, so the library reload signal only
    fires when a value actually changes.

    :param extensions_session: The PMM Extensions database session (``AppState`` + wrapper rows).
    :param celery_beat_session: The celery-beat database session (``PeriodicTask``).
    :param app_keys: Restrict the sweep to these app keys, or ``None`` for all.
    """
    rows = await ExtensionsAppPeriodicTaskManager.for_app_keys(
        extensions_session, app_keys
    )
    if not rows:
        return
    lifecycle_state = await AppStateManager.all_lifecycle_states(extensions_session)
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

    An unowned schedule gets no ``ExtensionsAppPeriodicTask`` wrapper row, so it has
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

    Startup entry point: opens one PMM Extensions session and one celery-beat session,
    upserts the wrapper rows, releases any schedule that no longer has an owner,
    then writes ``effective_enabled`` through for all owned schedules.

    :param system_tasks: The system periodic-task schedules to gate.
    """
    extensions_session_maker = get_extensions_session_maker()
    celery_beat_session_maker = get_celery_beat_session_maker()
    async with (
        extensions_session_maker() as extensions_session,
        celery_beat_session_maker() as celery_beat_session,
    ):
        await seed_app_periodic_task_rows(extensions_session, system_tasks)
        await release_unowned_task_gating(celery_beat_session, system_tasks)
        await apply_effective_enabled(extensions_session, celery_beat_session)


async def _collect_owned_task_names(
    session: AsyncSession, owners: Collection[str]
) -> set[str]:
    """Collect the names of the active tasks owned by the given apps.

    Loads only ``Task.name``, one keyset batch at a time, so no row's ``data``
    payload is transferred: schedules are matched by name alone.

    :param session: The Tasks database session.
    :param owners: The ``Task.owner`` values whose tasks to collect.
    :return: The names of every active task owned by ``owners``.
    """
    owned_names: set[str] = set()
    batches = TaskManager.iter_active_batches(
        session,
        col(Task.owner).in_(owners),
        batch_size=ACTIVE_TASK_BATCH_SIZE,
        query_options=[load_only(Task.name)],  # ty: ignore[invalid-argument-type]
    )
    async for batch in batches:
        owned_names.update(task.name for task in batch)
    return owned_names


async def _collect_owned_schedules(
    session: AsyncSession, owned_names: set[str]
) -> list[PeriodicTask]:
    """Collect the enabled schedules whose task is one of ``owned_names``.

    Pages by primary key rather than by offset so the batches stay disjoint and
    exhaustive while other writers insert, delete or switch off schedules, and
    holds only the matches across batches.

    :param session: The celery-beat database session.
    :param owned_names: The task names a schedule must resolve to.
    :return: The matching enabled schedules, in ascending id order.
    """
    schedules: list[PeriodicTask] = []
    last_schedule_id = 0
    while True:
        candidates = await PeriodicTaskManager.list(
            session,
            col(PeriodicTask.id) > last_schedule_id,
            enabled=True,
            order_by=[col(PeriodicTask.id)],
            limit=SCHEDULE_BATCH_SIZE,
        )
        for candidate in candidates:
            task_name = resolve_schedule_task_name(candidate)
            if task_name is None:
                logger.warning(
                    "Skipped periodic task %r: its args/kwargs do not name a task.",
                    candidate.name,
                )
            elif task_name in owned_names:
                schedules.append(candidate)
        if len(candidates) < SCHEDULE_BATCH_SIZE:
            break
        last_schedule_id = candidates[-1].id
    return schedules


async def disable_schedules_for_owners(
    tasks_session: AsyncSession,
    celery_beat_session: AsyncSession,
    owners: Collection[str],
) -> list[str]:
    """Switch off every enabled schedule whose task is owned by one of ``owners``.

    Resolve the task each enabled ``execute_task_by_name`` schedule runs from its
    ``args``/``kwargs`` the way the Tasks service reads them, and match it against
    the active tasks under ``owners``. A row whose arguments cannot be read is
    skipped with a warning, so one corrupt schedule cannot stop the rest from being
    switched off. The write is an ORM-instance mutation, so the library's
    ``after_update`` listener bumps ``PeriodicTaskChanged.last_update`` and a
    running scheduler reloads without a restart. Only enabled rows are selected, so
    a second run changes nothing.

    :param tasks_session: The Tasks database session (``Task``).
    :param celery_beat_session: The celery-beat database session (``PeriodicTask``).
    :param owners: The ``Task.owner`` values whose schedules to switch off.
    :return: The names of the schedules switched off, empty when none were.
    """
    if not owners:
        return []
    owned_names = await _collect_owned_task_names(tasks_session, owners)
    if not owned_names:
        return []
    schedules = await _collect_owned_schedules(celery_beat_session, owned_names)
    if not schedules:
        return []
    names: list[str] = [  # ty: ignore[invalid-assignment]
        schedule.name for schedule in schedules
    ]
    for schedule in schedules:
        schedule.enabled = False  # ty: ignore[invalid-assignment]
        celery_beat_session.add(schedule)
    await celery_beat_session.commit()
    for name in names:
        logger.warning(
            "Switched off periodic task %r: its task's app does not offer scheduling.",
            name,
        )
    return names


async def disable_unschedulable_task_schedules() -> None:
    """Switch off existing schedules of tasks whose app does not offer scheduling.

    Startup entry point. The owners come from the app registry, so no app is named
    here and an app absent from the activation list is not swept. No session is
    opened when no owner qualifies.
    """
    owners = get_app_registry().unschedulable_task_owners()
    if not owners:
        return
    tasks_session_maker = get_tasks_session_maker()
    celery_beat_session_maker = get_celery_beat_session_maker()
    async with (
        tasks_session_maker() as tasks_session,
        celery_beat_session_maker() as celery_beat_session,
    ):
        await disable_schedules_for_owners(tasks_session, celery_beat_session, owners)

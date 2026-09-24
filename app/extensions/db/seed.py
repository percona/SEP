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

"""Define the database initial data for the PMM Extensions app."""

import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import col

from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.extensions.apps.framework.registry import (
    app_celery_module_for,
    get_app_registry,
)
from app.extensions.config import extensions_settings
from app.extensions.crud import AppStateManager
from app.extensions.db import get_async_session_maker
from app.extensions.deps import PROTECTED_APP_KEYS
from app.extensions.models import AppLifecycleEnum, AppState, AppStateBase
from app.extensions.periodic_tasks import (
    disable_unschedulable_task_schedules,
    sync_app_periodic_task_gating,
)
from app.extensions.snippets.config import snippets_settings

logger = logging.getLogger(__name__)


def get_system_periodic_tasks() -> list[SystemPeriodicTaskSchedule]:
    """Build the PMM Extensions system periodic-task set, reading live settings per call.

    Computed on demand rather than baked into a module-level constant at import
    so a HOT settings override is reflected the next time the set is rebuilt (e.g. when
    the override refresh callback re-seeds the beat schedule), without an application
    restart. App-owned schedules come from each registry entry that declares
    ``periodic_task_schedules`` (a plain list or a factory returning one); a
    factory is invoked on every call, and each entry's ``schedule`` thunk is
    evaluated then so hot intervals are re-read.

    An app-owned schedule is emitted only when the owning app contributes a Celery
    module path (``App.celery_module_path``). An app absent from the activation
    list or opted out of the Celery ``include`` owns no registered task, so its
    schedule is skipped rather than seeded with a ``None``-prefixed ``task_name``
    that would point at nothing the worker imports. The seed path stamps
    ``owner_app_key`` from ``app.key`` and prefixes each entry's ``task`` with
    the resolved Celery module.

    Snippet ingestion is the carve-out: its task lives in the library
    (``app.extensions.snippets.celery``) and is named in ``STATIC_CELERY_INCLUDE``, so it
    registers whether or not the snippets app ships. Its schedule is therefore
    emitted unconditionally against the static path and carries no
    ``owner_app_key``, because disabling the snippets app must not gate it.

    A ``qualified`` spec names a complete task path and is emitted without that
    prefixing, so an app may own a schedule for a job the tasks service
    dispatches through ``execute_task_by_name``. Such an app owns no registered
    Celery task of its own, which is why the module lookup is scoped to the
    unqualified specs rather than gating the whole app. A spec whose thunk
    returns ``None`` contributes nothing this rebuild, which is how a nullable
    interval setting spells "do not run".

    :return: The schedule/task pairs to seed into the Celery beat database.
    """
    system_tasks = [
        SystemPeriodicTaskSchedule(
            schedule=extensions_settings.APP_DRAIN.reconcile_interval,
            tasks=[
                SystemPeriodicTaskData(
                    name="extensions__reconcile_disabling_apps",
                    task_name="app.extensions.app_drain.reconcile_disabling_apps",
                ),
            ],
        ),
    ]

    system_tasks.append(
        SystemPeriodicTaskSchedule(
            schedule=snippets_settings.SYNC_INTERVAL,
            tasks=[
                SystemPeriodicTaskData(
                    name="extensions__sync_snippets",
                    task_name="app.extensions.snippets.celery.sync_snippets",
                ),
            ],
        ),
    )

    for app in get_app_registry():
        if app.periodic_task_schedules is None:
            continue
        celery_module = app_celery_module_for(app.key)
        schedules = app.periodic_task_schedules
        specs = schedules if isinstance(schedules, list) else schedules()
        for spec in specs:
            if not spec.qualified and not celery_module:
                continue
            schedule = spec.schedule()
            if schedule is None:
                continue
            task_name = spec.task if spec.qualified else f"{celery_module}.{spec.task}"
            system_tasks.append(
                SystemPeriodicTaskSchedule(
                    schedule=schedule,
                    tasks=[
                        SystemPeriodicTaskData(
                            name=spec.name,
                            task_name=task_name,
                            extra_kwargs=spec.extra_kwargs,
                            owner_app_key=app.key,
                        ),
                    ],
                )
            )

    return system_tasks


async def init_extensions_db() -> None:
    """Initialize the PMM Extensions database with app state and periodic tasks.

    Seeds one :class:`app.extensions.models.AppState` row per non-protected, top-level
    plugin in ``EXTENSIONS.APPS`` using get-or-create (the YAML ``enabled`` flag is mapped
    to ``ENABLED`` / ``DISABLED`` only on insert; existing rows are never
    overwritten). Child apps (``parent_key`` set) are parent-bound and own no row
    of their own, so they are excluded here; a previously-seeded row for an app
    that has since become a child is removed by the orphan cleanup below. Removes
    rows for apps no longer configured, then seeds the PMM Extensions
    periodic tasks and gates each plugin-owned schedule by its app state via
    :func:`app.extensions.periodic_tasks.sync_app_periodic_task_gating`, and finally
    switches off every stored schedule whose task belongs to an app that does not
    offer scheduling via
    :func:`app.extensions.periodic_tasks.disable_unschedulable_task_schedules`.

    That last sweep is the only step here that reads the tasks database, and its
    failure is not fatal: the reconciliation is idempotent and only ever switches
    schedules off, so a skipped run self-heals at the next startup. A deployment
    whose ``extensions`` track has migrated ahead of its ``tasks`` track therefore boots
    and logs, rather than refusing to start.
    """
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        configured = [
            (app.key, app.enabled)
            for app in get_app_registry()
            if app.key not in PROTECTED_APP_KEYS and app.parent_key is None
        ]
        configured_keys = {key for key, _ in configured}
        existing_keys = set(await AppStateManager.all_lifecycle_states(session))
        for key, enabled in configured:
            if key in existing_keys:
                continue
            lifecycle_state = (
                AppLifecycleEnum.ENABLED if enabled else AppLifecycleEnum.DISABLED
            )
            await AppStateManager.create(
                session, AppStateBase(app_key=key, lifecycle_state=lifecycle_state)
            )
        orphan_keys = existing_keys - configured_keys
        if orphan_keys:
            await AppStateManager.delete_where(
                session, col(AppState.app_key).in_(orphan_keys)
            )
    system_tasks = get_system_periodic_tasks()
    await init_periodic_tasks_db(system_tasks, "extensions__")
    await sync_app_periodic_task_gating(system_tasks)
    try:
        await disable_unschedulable_task_schedules()
    except SQLAlchemyError:
        logger.exception(
            "Could not switch off unschedulable task schedules; starting anyway "
            "and leaving the sweep to the next startup."
        )

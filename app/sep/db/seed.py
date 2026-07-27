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

"""Define the database initial data for the SEP app."""

from sqlmodel import col

from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.sep.apps.framework.registry import app_celery_module_for, get_app_registry
from app.sep.config import sep_settings
from app.sep.crud import AppStateManager
from app.sep.db import get_async_session_maker
from app.sep.deps import PROTECTED_APP_KEYS
from app.sep.models import AppLifecycleEnum, AppState, AppStateBase
from app.sep.periodic_tasks import sync_app_periodic_task_gating


def get_system_periodic_tasks() -> list[SystemPeriodicTaskSchedule]:
    """Build the SEP system periodic-task set, reading live settings per call.

    Computed on demand rather than baked into a module-level constant at import
    so a HOT settings override is reflected the next time the set is rebuilt (e.g. when
    the override refresh callback re-seeds the beat schedule), without an application
    restart. App-owned schedules come from each registry entry that declares a
    ``periodic_task_schedules`` factory; the factory is invoked on every call.

    An app-owned schedule is emitted only when the owning app contributes a Celery
    module path (``App.celery_module_path``). An app absent from the activation
    list or opted out of the Celery ``include`` owns no registered task, so its
    schedule is skipped rather than seeded with a ``None``-prefixed ``task_name``
    that would point at nothing the worker imports.

    :return: The schedule/task pairs to seed into the Celery beat database.
    """
    system_tasks = [
        SystemPeriodicTaskSchedule(
            schedule=sep_settings.APP_DRAIN.reconcile_interval,
            tasks=[
                SystemPeriodicTaskData(
                    name="sep__reconcile_disabling_apps",
                    task_name="app.sep.app_drain.reconcile_disabling_apps",
                ),
            ],
        ),
    ]

    for app in get_app_registry():
        if app.periodic_task_schedules is None:
            continue
        if not app_celery_module_for(app.key):
            continue
        system_tasks.extend(app.periodic_task_schedules())

    return system_tasks


async def init_sep_db() -> None:
    """Initialize the SEP database with app state and periodic tasks.

    Seeds one :class:`app.sep.models.AppState` row per non-protected, top-level
    plugin in ``SEP.APPS`` using get-or-create (the YAML ``enabled`` flag is mapped
    to ``ENABLED`` / ``DISABLED`` only on insert; existing rows are never
    overwritten). Child apps (``parent_key`` set) are parent-bound and own no row
    of their own, so they are excluded here; a previously-seeded row for an app
    that has since become a child is removed by the orphan cleanup below. Removes
    rows for apps no longer configured, then seeds the SEP
    periodic tasks and gates each plugin-owned schedule by its app state via
    :func:`app.sep.periodic_tasks.sync_app_periodic_task_gating`.
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
    await init_periodic_tasks_db(system_tasks, "sep__")
    await sync_app_periodic_task_gating(system_tasks)

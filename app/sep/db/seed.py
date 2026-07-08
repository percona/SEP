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

import json

from sqlmodel import col

from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.sep.apps.framework.registry import get_app_registry
from app.sep.config import sep_settings
from app.sep.crud import AppStateManager
from app.sep.db import get_async_session_maker
from app.sep.deps import PROTECTED_APP_KEYS
from app.sep.models import AppLifecycleEnum, AppState, AppStateBase
from app.sep.periodic_tasks import sync_app_periodic_task_gating
from app.sep.snippets.config import snippets_settings

_alerts_plugin_enabled = any(
    p.module_name.endswith(".alerts") for p in sep_settings.APPS
)

_report_plugin_enabled = any(
    p.module_name.endswith(".report") for p in sep_settings.APPS
)


def get_system_periodic_tasks() -> list[SystemPeriodicTaskSchedule]:
    """Build the SEP system periodic-task set, reading live settings per call.

    Computed on demand rather than baked into a module-level constant at import
    so a HOT settings override is reflected the next time the set is rebuilt (e.g. when
    the override refresh callback re-seeds the beat schedule), without an application
    restart. The plugin-gated schedules (``alerts`` backup, ``report``
    generation) are keyed to their own settings and are included verbatim; their
    live-reload is not handled here and still requires a restart.

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
        SystemPeriodicTaskSchedule(
            schedule=snippets_settings.SYNC_INTERVAL,
            tasks=[
                SystemPeriodicTaskData(
                    name="sep__sync_snippets",
                    task_name="app.sep.celery.sync_snippets",
                    owner_app_key="snippets",
                ),
            ],
        ),
    ]

    if _alerts_plugin_enabled:
        from app.sep.apps.alerts.config import alerts_settings

        system_tasks.append(
            SystemPeriodicTaskSchedule(
                schedule=alerts_settings.BACKUP_INTERVAL,
                tasks=[
                    SystemPeriodicTaskData(
                        name="sep__backup_alert_config",
                        task_name="app.sep.celery.backup_alert_config",
                        owner_app_key="alerts",
                    ),
                ],
            ),
        )

    if _report_plugin_enabled:
        for idx, entry in enumerate(sep_settings.HEALTH_REPORT.schedules):
            suffix = f"_{idx}" if idx else ""
            task_kwargs = {}
            if entry.since != "now-7d":
                task_kwargs["since"] = entry.since
            if entry.until != "now":
                task_kwargs["until"] = entry.until
            if not entry.full:
                task_kwargs["full"] = entry.full
            if entry.refresh:
                task_kwargs["refresh"] = entry.refresh
            if entry.sections is not None:
                task_kwargs["sections"] = entry.sections
            if entry.upload:
                task_kwargs["upload"] = entry.upload
            system_tasks.append(
                SystemPeriodicTaskSchedule(
                    schedule=entry.schedule,
                    tasks=[
                        SystemPeriodicTaskData(
                            name=f"sep__generate_health_report{suffix}",
                            task_name="app.sep.apps.report.celery.generate_health_report",
                            extra_kwargs={"kwargs": json.dumps(task_kwargs)}
                            if task_kwargs
                            else None,
                            owner_app_key="report",
                        ),
                    ],
                ),
            )

        system_tasks.append(
            SystemPeriodicTaskSchedule(
                schedule=sep_settings.HEALTH_REPORT.cleanup_interval,
                tasks=[
                    SystemPeriodicTaskData(
                        name="sep__purge_report_artifacts",
                        task_name="app.sep.apps.report.celery.purge_report_artifacts",
                        owner_app_key="report",
                    ),
                ],
            ),
        )

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

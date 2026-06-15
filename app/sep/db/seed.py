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
from app.sep.config import sep_settings
from app.sep.crud import AppStateManager
from app.sep.db import get_async_session_maker
from app.sep.deps import PROTECTED_APP_KEYS
from app.sep.models import AppState, AppStateBase
from app.sep.periodic_tasks import sync_app_periodic_task_gating
from app.sep.plugins.framework.registry import get_app_registry
from app.sep.snippets.config import snippets_settings

_alerts_plugin_enabled = any(
    p.module_name.endswith(".alerts") for p in sep_settings.PLUGINS
)

_report_plugin_enabled = any(
    p.module_name.endswith(".report") for p in sep_settings.PLUGINS
)

SYSTEM_PERIODIC_TASKS = [
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
    from app.sep.plugins.alerts.config import alerts_pmm_config

    SYSTEM_PERIODIC_TASKS.append(
        SystemPeriodicTaskSchedule(
            schedule=alerts_pmm_config.backup_interval,
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
    for _idx, _entry in enumerate(sep_settings.HEALTH_REPORT.schedules):
        _suffix = f"_{_idx}" if _idx else ""
        _task_kwargs = {}
        if _entry.since != "now-7d":
            _task_kwargs["since"] = _entry.since
        if _entry.until != "now":
            _task_kwargs["until"] = _entry.until
        if not _entry.full:
            _task_kwargs["full"] = _entry.full
        if _entry.refresh:
            _task_kwargs["refresh"] = _entry.refresh
        if _entry.sections is not None:
            _task_kwargs["sections"] = _entry.sections
        if _entry.upload:
            _task_kwargs["upload"] = _entry.upload
        SYSTEM_PERIODIC_TASKS.append(
            SystemPeriodicTaskSchedule(
                schedule=_entry.schedule,
                tasks=[
                    SystemPeriodicTaskData(
                        name=f"sep__generate_health_report{_suffix}",
                        task_name="app.sep.celery.generate_health_report",
                        extra_kwargs={"kwargs": json.dumps(_task_kwargs)}
                        if _task_kwargs
                        else None,
                        owner_app_key="report",
                    ),
                ],
            ),
        )


async def init_sep_db() -> None:
    """Initialize the SEP database with app state and periodic tasks.

    Seeds one :class:`app.sep.models.AppState` row per non-protected plugin in
    ``SEP.PLUGINS`` using get-or-create (the YAML ``enabled`` value is read only
    on insert; existing rows are never overwritten), removes rows for apps no
    longer configured, then seeds the SEP periodic tasks and gates each
    plugin-owned schedule by its app state via
    :func:`app.sep.periodic_tasks.sync_app_periodic_task_gating`.
    """
    async_session_maker = get_async_session_maker()
    async with async_session_maker() as session:
        configured = [
            (app.key, app.enabled)
            for app in get_app_registry()
            if app.key not in PROTECTED_APP_KEYS
        ]
        configured_keys = {key for key, _ in configured}
        existing_keys = set(await AppStateManager.all_states(session))
        for key, enabled in configured:
            if key in existing_keys:
                continue
            await AppStateManager.create(
                session, AppStateBase(app_key=key, enabled=enabled)
            )
        orphan_keys = existing_keys - configured_keys
        if orphan_keys:
            await AppStateManager.delete_where(
                session, col(AppState.app_key).in_(orphan_keys)
            )
    await init_periodic_tasks_db(SYSTEM_PERIODIC_TASKS, "sep__")
    await sync_app_periodic_task_gating(SYSTEM_PERIODIC_TASKS)

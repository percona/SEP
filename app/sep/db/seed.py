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

from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.sep.config import sep_settings
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
                    ),
                ],
            ),
        )


async def create_plugin_tables() -> None:
    """Create database tables for plugin-scoped models when the corresponding plugin is enabled.

    Safe to call repeatedly as ``checkfirst=True`` is the default for
    ``create_all``.
    """
    if not _alerts_plugin_enabled:
        return

    from sqlmodel import SQLModel

    from app.sep.db.engine import engine
    from app.sep.plugins.alerts.backup import AlertBackup

    async with engine.begin() as conn:
        await conn.run_sync(
            SQLModel.metadata.create_all,
            tables=[AlertBackup.__table__],
        )


async def init_sep_db() -> None:
    """Initialize the SEP database with periodic tasks."""
    await init_periodic_tasks_db(SYSTEM_PERIODIC_TASKS, "sep__")

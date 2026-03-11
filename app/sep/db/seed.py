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

from app.core.celery.utils import (
    init_periodic_tasks_db,
    SystemPeriodicTaskData,
    SystemPeriodicTaskSchedule,
)
from app.sep.config import sep_settings
from app.sep.snippets.config import snippets_settings

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
    SystemPeriodicTaskSchedule(
        schedule=sep_settings.PMM.backup_interval,
        tasks=[
            SystemPeriodicTaskData(
                name="sep__backup_alert_config",
                task_name="app.sep.celery.backup_alert_config",
            ),
        ],
    ),
]


async def create_plugin_tables() -> None:
    """Create database tables for plugin-scoped models.

    Create tables that are only needed when specific plugins are enabled.
    Safe to call repeatedly as ``checkfirst=True`` is the default for
    ``create_all``.

    Import plugin models and engine inline to avoid triggering SQLModel
    metadata side-effects at module load time.
    """
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

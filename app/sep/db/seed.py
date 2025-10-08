# Copyright (C) 2025 Percona LLC
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
    )
]


async def init_sep_db() -> None:
    """Initialize the SEP database with periodic tasks."""
    await init_periodic_tasks_db(SYSTEM_PERIODIC_TASKS, "sep__")

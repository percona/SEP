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

"""Wire the Health & Security Report plugin as a declarative ``BaseApp``.

Register the bespoke report plugin through the registry's definition path
instead of the synthesized-legacy fallback, exposing the same JSON and Jinja
routers the registry imports today, and contribute the health-report generation
and artifact-purge beat schedules via ``periodic_task_schedules``.
"""

import json

from app.sep.apps.framework.base import AppPeriodicTask, BaseApp
from app.sep.apps.nav_icons import NavIcon
from app.sep.apps.report.api_routes import router as api_router
from app.sep.apps.report.routes import router as jinja_router
from app.sep.config import sep_settings


def _report_periodic_tasks() -> list[AppPeriodicTask]:
    """Expand one generation task per configured health-report schedule entry.

    Kept as a callable because ``HEALTH_REPORT.schedules`` is variable-length;
    each entry's interval is deferred via the ``schedule`` thunk so a hot
    override is visible on the next seed.

    :return: One generation contrib per schedule entry, plus the artifact-purge
        contrib.
    """
    tasks: list[AppPeriodicTask] = []
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
        tasks.append(
            AppPeriodicTask(
                name=f"sep__generate_health_report{suffix}",
                task="generate_health_report",
                schedule=lambda e=entry: e.schedule,
                extra_kwargs={"kwargs": json.dumps(task_kwargs)}
                if task_kwargs
                else None,
            ),
        )

    tasks.append(
        AppPeriodicTask(
            name="sep__purge_report_artifacts",
            task="purge_report_artifacts",
            schedule=lambda: sep_settings.HEALTH_REPORT.cleanup_interval,
        ),
    )
    return tasks


app = BaseApp(
    name="report",
    display_name="Health & Security Report",
    uri_path="/report",
    css_class="report",
    group="diagnostics",
    nav_order=13,
    react_route="/reports",
    nav_icon=NavIcon.BAR_CHART,
    api_router=api_router,
    jinja_router=jinja_router,
    periodic_task_schedules=_report_periodic_tasks,
)

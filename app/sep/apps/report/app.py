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

from app.core.celery.utils import SystemPeriodicTaskData, SystemPeriodicTaskSchedule
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.framework.registry import app_celery_module_for
from app.sep.apps.nav_icons import NavIcon
from app.sep.apps.report.api_routes import router as api_router
from app.sep.apps.report.routes import router as jinja_router
from app.sep.config import sep_settings


def _report_periodic_tasks() -> list[SystemPeriodicTaskSchedule]:
    """Build the health-report generation and artifact-purge schedules.

    :return: One generation schedule per configured health-report entry, followed
        by the artifact-purge schedule, or an empty list when report owns no
        Celery module.
    """
    report_celery = app_celery_module_for("report")
    if not report_celery:
        return []

    schedules = []
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
        schedules.append(
            SystemPeriodicTaskSchedule(
                schedule=entry.schedule,
                tasks=[
                    SystemPeriodicTaskData(
                        name=f"sep__generate_health_report{suffix}",
                        task_name=f"{report_celery}.generate_health_report",
                        extra_kwargs={"kwargs": json.dumps(task_kwargs)}
                        if task_kwargs
                        else None,
                        owner_app_key="report",
                    ),
                ],
            ),
        )

    schedules.append(
        SystemPeriodicTaskSchedule(
            schedule=sep_settings.HEALTH_REPORT.cleanup_interval,
            tasks=[
                SystemPeriodicTaskData(
                    name="sep__purge_report_artifacts",
                    task_name=f"{report_celery}.purge_report_artifacts",
                    owner_app_key="report",
                ),
            ],
        ),
    )
    return schedules


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

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

"""Wire the Alert Templates plugin as a declarative ``BaseApp``.

Register the bespoke alerts plugin through the registry's definition path
(``getattr(module, "app")``) instead of the synthesized-legacy fallback,
exposing the same JSON and Jinja routers the registry imports today, and
contribute the alert-config backup beat schedule via
``periodic_task_schedules``.
"""

from app.sep.apps.alerts.api_routes import router as api_router
from app.sep.apps.alerts.config import alerts_settings
from app.sep.apps.alerts.routes import router as jinja_router
from app.sep.apps.framework.base import AppPeriodicTask, BaseApp
from app.sep.apps.nav_icons import NavIcon

app = BaseApp(
    name="alerts",
    display_name="Alert Templates",
    uri_path="/alerts",
    css_class="alerts",
    group="alerts",
    nav_order=4,
    react_route="/alerts/templates",
    nav_icon=NavIcon.DESCRIPTION,
    api_router=api_router,
    jinja_router=jinja_router,
    periodic_task_schedules=[
        AppPeriodicTask(
            name="sep__backup_alert_config",
            task="backup_alert_config",
            schedule=lambda: alerts_settings.BACKUP_INTERVAL,
        ),
    ],
)

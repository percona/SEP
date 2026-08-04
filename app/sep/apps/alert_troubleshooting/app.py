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

"""Wire the Alert Troubleshooting plugin as a declarative ``BaseApp``.

alert_troubleshooting projects alerts out of snippet frontmatter and exposes a
composite-keyed JSON surface — alerts grouped by service type and a
``(service_type, alert_name)`` detail with linked snippets — plus a deprecated
Jinja UI whose ``POST /execute`` reuses the snippets execution path. None of that
maps onto the framework's filename-keyed ``ScriptSource`` derived routes, so it is
exported as a plain :class:`BaseApp` carrying its hand-written ``api_router``
unchanged, the same shape as ``dipper`` and the bespoke ``inventory``/``report``
apps. The legacy Jinja UI is threaded as ``jinja_router``.
"""

from app.sep.apps.alert_troubleshooting.api_routes import router as api_router
from app.sep.apps.alert_troubleshooting.routes import router as jinja_router
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.nav_icons import NavIcon

app = BaseApp(
    name="alert_troubleshooting",
    display_name="Alert Troubleshooting",
    uri_path="/alert-troubleshooting",
    css_class="alert-troubleshooting",
    group="alerts",
    nav_order=5,
    react_route="/alerts/troubleshooting",
    nav_icon=NavIcon.TROUBLESHOOT,
    api_router=api_router,
    jinja_router=jinja_router,
    uses_task_data=True,
)

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

"""Wire the Tasks plugin as a declarative ``BaseApp``.

Register the read-only cross-owner task viewer through the registry's
definition path instead of the synthesized-legacy fallback, carrying its
``TASKS_PLUGIN_SCHEMA`` so the conformance suite reads the schema from the
definition rather than the live ``GET /schema`` endpoint.
"""

from app.sep.apps.framework.base import BaseApp
from app.sep.apps.nav_icons import NavIcon
from app.sep.apps.tasks.api_routes import router as api_router
from app.sep.apps.tasks.routes import router as jinja_router
from app.sep.apps.tasks.schema import TASKS_PLUGIN_SCHEMA

app = BaseApp(
    name="tasks",
    display_name="Task Manager",
    uri_path="/tasks",
    css_class="tasks",
    nav_order=1,
    react_route="/tasks",
    nav_icon=NavIcon.ASSIGNMENT,
    api_router=api_router,
    jinja_router=jinja_router,
    schema=TASKS_PLUGIN_SCHEMA,
    uses_task_data=True,
)

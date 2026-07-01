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
routers the registry imports today.
"""

from app.sep.apps.framework.base import BaseApp
from app.sep.apps.report.api_routes import router as api_router
from app.sep.apps.report.routes import router as jinja_router

app = BaseApp(
    name="report",
    display_name="Health & Security Report",
    uri_path="/report",
    css_class="report",
    group="diagnostics",
    nav_order=13,
    api_router=api_router,
    jinja_router=jinja_router,
)

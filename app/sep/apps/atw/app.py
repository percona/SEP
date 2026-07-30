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

"""Wire the ATW plugin as a declarative ``BaseApp``.

Register ``atw`` ("Collect Diagnostic Data") through the registry's definition
path, carrying the existing JSON ``api_router`` (the category listing + schema)
and ``atw_schema`` so the conformance suite reads the schema from the definition.
``atw`` owns no task and derives no execute route -- execution is delegated to the
snippets ``ScriptSource`` surface, consumed by the React ``AtwPage``. It nests
under the shared ``snippets`` nav group alongside the snippets app.
"""

from app.sep.apps.atw.api_routes import router as api_router
from app.sep.apps.atw.schema import atw_schema
from app.sep.apps.framework.base import BaseApp
from app.sep.apps.nav_icons import NavIcon

app = BaseApp(
    name="atw",
    display_name="Collect Diagnostic Data",
    uri_path="/atw",
    css_class="atw",
    custom_ui=True,
    group="diagnostics",
    nav_order=3,
    react_route="/atw",
    nav_icon=NavIcon.SUPPORT_AGENT,
    api_router=api_router,
    schema=atw_schema,
    requires_apps=("snippets",),
)

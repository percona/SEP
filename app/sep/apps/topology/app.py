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

"""Wire the Topology plugin as a declarative ``BaseApp``.

Topology renders a bespoke React Flow graph, so it ships a hand-written
``api_router`` and a custom UI rather than the framework's schema-driven
surface. Enablement is purely a function of app registration (``SEP.APPS``);
there is no separate feature flag.
"""

from app.sep.apps.framework.base import BaseApp
from app.sep.apps.nav_icons import NavIcon
from app.sep.apps.topology.api_routes import router as api_router

app = BaseApp(
    name="topology",
    display_name="Topology",
    uri_path="/topology",
    css_class="topology",
    group="diagnostics",
    nav_order=13,
    nav_icon=NavIcon.ACCOUNT_TREE,
    custom_ui=True,
    api_router=api_router,
)

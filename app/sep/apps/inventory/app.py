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

"""Wire the Inventory plugin as a declarative ``BaseApp``.

Register the bespoke inventory plugin through the registry's definition path
instead of the synthesized-legacy fallback, carrying its existing
``inventory_schema`` so the conformance suite reads the schema from the
definition rather than the live ``GET /schema`` endpoint.
"""

from app.sep.apps.framework.base import BaseApp
from app.sep.apps.inventory.api_routes import router as api_router
from app.sep.apps.inventory.schema import inventory_schema

app = BaseApp(
    name="inventory",
    display_name="Inventory",
    uri_path="/inventory",
    css_class="inventory",
    api_router=api_router,
    schema=inventory_schema,
)

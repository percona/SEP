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

"""Wire the Golden Base plugin as a declarative API-first ``BaseApp``.

The registry mounts the exported ``app``'s ``api_router`` under
``/api/apps/golden_base`` and serves its ``schema``. ``custom_ui=True`` marks
that the app ships a bespoke React UI rather than the schema-driven one.
"""

from app.sep.apps.framework.base import BaseApp
from app.sep.apps.golden_base.api_routes import router as api_router
from app.sep.apps.golden_base.schema import golden_base_schema

app = BaseApp(
    name="golden_base",
    display_name="Golden Base",
    uri_path="/golden_base",
    css_class="golden_base",
    api_router=api_router,
    schema=golden_base_schema,
    custom_ui=True,
)

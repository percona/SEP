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

"""Wire the Alters (Schema Change) plugin as a registry ``BaseApp``.

alters keeps a hand-written JSON ``api_router``: its list shows only the parent
execute tasks (the ``-dry-run`` / ``-pre-checks`` satellites share ``owner=alters``
and are filtered out), and its detail resolves a satellite name back to its parent
— neither expressible through the framework's always-on derived read routes — so it
is exported as a plain :class:`BaseApp` rather than a ``TaskExecutionApp``. The
schema is still derived model-first from
:class:`~app.sep.plugins.alters.models.AltersCreate` and served by the
``api_router``'s ``GET /schema``; the cascade create/update/delete routes compose
the app-local ``cascade_*_alters_group`` helpers. The descriptive metadata
(``display_name`` / ``uri_path`` / ``css_class`` / ``group`` / ``nav_order``) is
carried here because ``settings.yaml`` no longer does; ``display_name`` is
``"Schema Change"``, the navigation label, distinct from the schema's ``"Alters"``.
The Jinja UI router is threaded explicitly as ``jinja_router``.
"""

from app.sep.plugins.alters.api_routes import router as api_router
from app.sep.plugins.alters.routes import router as jinja_router
from app.sep.plugins.framework.base import BaseApp

app = BaseApp(
    name="alters",
    display_name="Schema Change",
    uri_path="/alters",
    css_class="alters",
    nav_order=6,
    api_router=api_router,
    jinja_router=jinja_router,
)

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

"""Wire the MongoDB Backups plugin as a registry ``BaseApp``.

backup_mongo keeps a hand-written JSON ``api_router``: its list shows only the parent
``pbm_config`` tasks, and its detail aggregates the derived sibling statuses plus the
latest PBM-status tail — neither expressible through the framework's always-on derived
read routes — so it is exported as a plain :class:`BaseApp` rather than a
``TaskExecutionApp``. The schema is still derived model-first from
:class:`~app.sep.apps.backup_mongo.models.BackupForm` and served by the
``api_router``'s ``GET /schema``; the cascade create/delete routes compose the frozen
``cascade_*`` helpers. The descriptive metadata (``display_name`` / ``uri_path`` /
``css_class`` / ``group`` / ``nav_order``) is carried here because ``settings.yaml`` no
longer does. The Jinja UI router is threaded explicitly as ``jinja_router``.
"""

from app.sep.apps.backup_mongo.api_routes import router as api_router
from app.sep.apps.backup_mongo.routes import router as jinja_router
from app.sep.apps.framework.base import BaseApp

app = BaseApp(
    name="backup_mongo",
    display_name="MongoDB Backups",
    uri_path="/backup_mongo",
    css_class="backup_mongo",
    group="backups",
    nav_order=9,
    api_router=api_router,
    jinja_router=jinja_router,
)

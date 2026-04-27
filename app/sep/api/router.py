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

"""Define the shared SEP API router hosting plugin endpoints.

Apply authentication at the router level and expose per-plugin sub-routers
under ``/api/plugins/{plugin_name}/``. Per-plugin routers are added in their
own tickets; this module only defines the composition skeleton.

``/api/plugins/*`` reaches ``sep_app`` because the top-level ``app/main.py``
mounts ``/api/inventory`` and ``/api/tasks`` before ``/`` — nothing more
specific claims ``/api/plugins``. A future ``app.mount("/api/plugins", ...)``
in ``app/main.py`` would silently shadow this router.
"""

from fastapi import APIRouter

from app.sep.deps import IsApiAuthenticated
from app.sep.plugins.checksums.api_routes import router as checksums_api_router

plugins_router = APIRouter(prefix="/plugins")
plugins_router.include_router(
    checksums_api_router, prefix="/checksums", tags=["checksums"]
)

api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
api_router.include_router(plugins_router)

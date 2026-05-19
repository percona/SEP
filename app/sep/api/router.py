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

"""Define the shared SEP API router hosting plugin and cross-cutting endpoints.

Apply authentication at the router level and expose two prefix groups:

* ``/api/plugins/{plugin_name}/`` — per-plugin JSON endpoints (added in
  individual plugin tickets).
* ``/api/sep/...`` — cross-cutting JSON endpoints that proxy to the Tasks and
  Inventory sub-applications (so the frontend never bypasses the SEP layer).

``/api/plugins/*`` and ``/api/sep/*`` reach ``sep_app`` because the top-level
``app/main.py`` mounts ``/api/inventory`` and ``/api/tasks`` before ``/`` —
nothing more specific claims either prefix. A future
``app.mount("/api/plugins", ...)`` or ``app.mount("/api/sep", ...)`` in
``app/main.py`` would silently shadow this router.
"""

from collections.abc import Iterable

from fastapi import APIRouter

from app.core.utils import import_var
from app.sep.api.routes.dashboard import router as dashboard_router
from app.sep.api.routes.hosts import router as hosts_router
from app.sep.config import Plugin, sep_settings
from app.sep.deps import IsApiAuthenticated


def build_plugins_router(plugins: Iterable[Plugin]) -> APIRouter:
    """Build the ``/plugins`` sub-router by iterating ``plugins``.

    Mirror the Jinja UI mount loop in ``app/sep/main.py`` so future
    runtime enable/disable guards (SEP-982) can be applied symmetrically at
    both mount points.

    :param plugins: Iterable of ``Plugin`` settings entries.
    :type plugins: Iterable[Plugin]
    :return: An ``APIRouter`` mounted at ``/plugins`` with each plugin whose
        ``api_router_path`` is set included at ``/{key}`` with ``tags=[key]``.
    :rtype: APIRouter
    """
    plugins_router = APIRouter(prefix="/plugins")
    for plugin in plugins:
        if not plugin.api_router_path:
            continue
        key = plugin.module_name.split(".")[-1]
        plugin_api_router = import_var(plugin.api_router_path)
        if not isinstance(plugin_api_router, APIRouter):
            raise TypeError(
                f"Plugin '{key}': '{plugin.api_router_path}' must resolve to an"
                f" APIRouter, got {type(plugin_api_router).__name__}"
            )
        plugins_router.include_router(plugin_api_router, prefix=f"/{key}", tags=[key])
    return plugins_router


plugins_router = build_plugins_router(sep_settings.PLUGINS)

api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
api_router.include_router(plugins_router)
api_router.include_router(dashboard_router, prefix="/sep/dashboard", tags=["sep"])
api_router.include_router(hosts_router, prefix="/sep/hosts", tags=["sep"])

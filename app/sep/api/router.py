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

from fastapi import APIRouter, Depends

from app.sep.api.routes.app_info import router as app_info_router
from app.sep.api.routes.app_state import router as app_state_router
from app.sep.api.routes.apps import router as apps_router
from app.sep.api.routes.dashboard import router as dashboard_router
from app.sep.api.routes.hosts import router as hosts_router
from app.sep.api.routes.periodic_tasks import router as periodic_tasks_router
from app.sep.api.routes.schemas import router as schemas_router
from app.sep.api.routes.services import router as services_router
from app.sep.api.routes.settings import router as settings_router
from app.sep.api.routes.task_history import router as task_history_router
from app.sep.api.routes.task_stats import router as task_stats_router
from app.sep.plugins.mongo_upgrade.routes import router as mongo_upgrade_router
from app.sep.deps import (
    IsApiAdmin,
    IsApiAuthenticated,
    PROTECTED_APP_KEYS,
    require_app_enabled,
    RequireBearerForUnsafeMethods,
)
from app.sep.plugins.framework.registry import AppRegistry, get_app_registry


def build_plugins_router(registry: AppRegistry) -> APIRouter:
    """Build the ``/plugins`` sub-router by iterating the app registry.

    Mirror the Jinja UI mount loop in ``app/sep/main.py`` so future
    runtime enable/disable guards can be applied symmetrically at both
    mount points.

    :param registry: The app registry, in activation order.
    :type registry: AppRegistry
    :return: An ``APIRouter`` mounted at ``/plugins`` with each app whose
        ``api_router`` is set included at ``/{key}`` with ``tags=[key]``.
    :rtype: APIRouter
    """
    plugins_router = APIRouter(
        prefix="/plugins", dependencies=[RequireBearerForUnsafeMethods]
    )
    for app in registry:
        if app.api_router is None:
            continue
        plugin_deps = (
            []
            if app.key in PROTECTED_APP_KEYS
            else [Depends(require_app_enabled(app.key))]
        )
        plugins_router.include_router(
            app.api_router,
            prefix=f"/{app.key}",
            tags=[app.key],
            dependencies=plugin_deps,
        )
    return plugins_router


plugins_router = build_plugins_router(get_app_registry())

api_router = APIRouter(prefix="/api", dependencies=[IsApiAuthenticated])
api_router.include_router(plugins_router)
api_router.include_router(app_info_router, prefix="/sep/app-info", tags=["sep"])
api_router.include_router(dashboard_router, prefix="/sep/dashboard", tags=["sep"])
api_router.include_router(hosts_router, prefix="/sep/hosts", tags=["sep"])
api_router.include_router(services_router, prefix="/sep/services", tags=["sep"])
api_router.include_router(schemas_router, prefix="/sep/schemas", tags=["sep"])
api_router.include_router(settings_router, prefix="/sep/admin/settings", tags=["sep"])
api_router.include_router(task_stats_router, prefix="/sep/task-stats", tags=["sep"])
api_router.include_router(task_history_router, prefix="/sep/task-history", tags=["sep"])
api_router.include_router(
    periodic_tasks_router,
    prefix="/sep/periodic-tasks",
    tags=["sep"],
    dependencies=[RequireBearerForUnsafeMethods],
)
api_router.include_router(
    app_state_router,
    prefix="/admin/apps",
    tags=["admin"],
    dependencies=[IsApiAdmin, RequireBearerForUnsafeMethods],
)
api_router.include_router(apps_router, prefix="/apps", tags=["apps"])
api_router.include_router(
    mongo_upgrade_router,
    prefix="/sep/mongo-upgrade",
    tags=["mongo-upgrade"],
)

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

"""Define the shared ``/schema`` discovery endpoint helper for plugin routers."""

from fastapi import APIRouter

from app.sep.deps import IsApiAuthenticated
from app.sep.plugins.framework.schema import PluginSchema

__all__ = ["schema_endpoint"]


def schema_endpoint(router: APIRouter, plugin_schema: PluginSchema) -> None:
    """Register a ``GET /schema`` route on ``router`` that returns ``plugin_schema``.

    Call this once from the module that owns the plugin's ``APIRouter``
    (typically under the shared ``plugins_router`` tree in
    ``app/sep/api/router.py``); the route then resolves at
    ``/api/plugins/{plugin}/schema`` once the plugin router is included with
    the matching prefix. The helper itself does not set a prefix.

    .. code-block:: python

        from fastapi import APIRouter

        from app.sep.plugins.framework.api import schema_endpoint
        from app.sep.plugins.checksums.schema import checksums_schema

        router = APIRouter()
        schema_endpoint(router, checksums_schema)

    The route pins ``response_model_by_alias=True`` and redeclares
    ``IsApiAuthenticated`` at the route level even though ``api_router``
    applies the same dependency at router level; the duplicate declaration
    guarantees a JSON 401 even if a plugin mounts the router outside that
    tree, and FastAPI's dependency cache deduplicates it per request.

    :param router: The plugin's ``APIRouter``.
    :type router: APIRouter
    :param plugin_schema: The plugin's fully-validated schema instance.
    :type plugin_schema: PluginSchema
    :raises ValueError: If ``router`` already exposes a ``GET /schema`` route.
    """
    for existing in router.routes:
        if getattr(existing, "path", None) == "/schema" and "GET" in getattr(
            existing, "methods", set()
        ):
            raise ValueError(
                "schema_endpoint: router already has a GET /schema route; "
                "call this helper at most once per plugin router"
            )

    @router.get(
        "/schema",
        response_model=PluginSchema,
        response_model_by_alias=True,
        dependencies=[IsApiAuthenticated],
    )
    async def get_schema() -> PluginSchema:
        """Return the plugin schema captured at registration time.

        :return: The plugin schema instance.
        :rtype: PluginSchema
        """
        return plugin_schema

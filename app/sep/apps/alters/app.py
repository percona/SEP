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

"""Wire the Alters (Schema Change) plugin as a declarative ``TaskExecutionApp``.

Only the ``GET /schema`` and paginated list routes are derived: the list sets
``list_filter=ListFilterConfig(roots_only=True)`` so the server-side
``parent_is_null=true`` filter hides the ``-dry-run`` / ``-pre-checks`` satellites
that share ``owner=alters``, and its rows are built by
:func:`~app.sep.apps.alters.deps.build_alters_api_list_response`. Every mutation is
kept per-app: all :class:`~app.sep.apps.framework.apps.AppCapabilities` are off and
the satellite-resolving detail, cascade create/update/delete, and execute routes
ride the ``extra_routes`` router. ``capabilities.detail=False`` suppresses the
greedy derived detail so the custom ``GET /{task_name}`` wins. The schema is the
model-first :data:`~app.sep.apps.alters.schema.alters_schema` passed through
verbatim, so its ``display_name`` stays ``"Alters"`` — distinct from the navigation
label ``"Schema Change"`` carried here. The Jinja UI router is threaded explicitly.
"""

from app.core.pagination.deps import make_pagination_dep
from app.inventory.models import ServiceTypeEnum
from app.sep.apps.alters.api_routes import router as alters_custom_router
from app.sep.apps.alters.deps import build_alters_api_list_response, get_alters_task
from app.sep.apps.alters.models import AltersTaskResponse, OWNER
from app.sep.apps.alters.routes import router as jinja_router
from app.sep.apps.alters.schema import alters_schema
from app.sep.apps.framework.apps import (
    AppCapabilities,
    ListFilterConfig,
    TaskExecutionApp,
)
from app.sep.deps import get_username_mapping

ALTERS_MAX_PAGINATION_LIMIT = 50

app = TaskExecutionApp(
    name="alters",
    display_name="Schema Change",
    uri_path="/alters",
    css_class="alters",
    nav_order=6,
    owner=OWNER,
    schema=alters_schema,
    response_model=AltersTaskResponse,
    response_builder=build_alters_api_list_response,
    response_context_provider=get_username_mapping,
    get_task=get_alters_task,
    pagination=make_pagination_dep(max_limit=ALTERS_MAX_PAGINATION_LIMIT),
    service_type=ServiceTypeEnum.MYSQL,
    list_filter=ListFilterConfig(status=True, service_type=True, roots_only=True),
    capabilities=AppCapabilities(
        create=False, detail=False, execute=False, update=False, delete=False
    ),
    extra_routes=(alters_custom_router,),
    jinja_router=jinja_router,
)

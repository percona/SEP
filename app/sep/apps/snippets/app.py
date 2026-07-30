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

"""Wire the Snippets plugin as a declarative ``TaskExecutionApp``.

The registry discovers the exported ``app`` under the key ``snippets`` (derived
from the module path), mounting its derived JSON router at
``/api/apps/snippets/`` while the existing Jinja UI keeps serving at
``/snippets/`` via the threaded ``jinja_router``. The JSON surface is the first
real adoption of the framework ``ScriptSource`` seam: listing, per-snippet form
schema, execution history, and execute are derived from
:data:`~app.sep.apps.snippets.script_source.snippet_source`, while the
non-derived auxiliary verbs (approval, manual refresh, preview/download) are
carried as ``extra_routes``. ``GET /capabilities`` is wired through the framework
``capabilities_provider`` helper.

``owner=ANY_OWNER``: a script app's derived routes never consume the owner
(it only seeds the unused per-owner task dependency), and snippets declares no
owner of its own — ``ANY`` is the honest "no owner restriction" value. The
snippets sync beat schedule is contributed via ``periodic_task_schedules``.
"""

from app.sep.apps.framework.apps import TaskExecutionApp
from app.sep.apps.framework.base import AppPeriodicTask
from app.sep.apps.nav_icons import NavIcon
from app.sep.apps.snippets.constants import ARTIFACT_TYPE_SNIPPET
from app.sep.apps.snippets.extra_routes import (
    approval_router,
    artifact_router,
    maintenance_router,
)
from app.sep.apps.snippets.models import SnippetsCapabilitiesResponse
from app.sep.apps.snippets.routes import router as jinja_router
from app.sep.apps.snippets.script_source import snippet_source
from app.sep.snippets.config import snippets_settings
from app.tasks.models import ANY_OWNER


def _snippets_capabilities_provider() -> SnippetsCapabilitiesResponse:
    """Return per-deployment capability flags for the snippets plugin.

    Read live from ``snippets_settings`` so a deployment-config hot reload between
    two requests is reflected on the next response.

    :return: Capability flags reflecting the current deployment config.
    """
    return SnippetsCapabilitiesResponse(
        manual_sync_enabled=snippets_settings.ENABLE_MANUAL_SYNC,
    )


app = TaskExecutionApp(
    name="snippets",
    display_name="Snippet Manager",
    uri_path="/snippets",
    css_class="snippets",
    nav_order=2,
    react_route="/snippets",
    nav_icon=NavIcon.CODE,
    description="Browse, approve, and execute operational snippets.",
    owner=ANY_OWNER,
    script_source=snippet_source,
    capabilities_provider=_snippets_capabilities_provider,
    extra_routes=(approval_router, maintenance_router, artifact_router),
    jinja_router=jinja_router,
    artifact_base_dirs={ARTIFACT_TYPE_SNIPPET: lambda: snippets_settings.SNIPPETS_DIR},
    periodic_task_schedules=[
        AppPeriodicTask(
            name="sep__sync_snippets",
            task="sync_snippets",
            schedule=lambda: snippets_settings.SYNC_INTERVAL,
        ),
    ],
)

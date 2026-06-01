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

"""Public app listing endpoint for the React shell.

Mounted under ``/api/apps/``. Authentication is enforced by the parent
``api_router`` (``IsApiAuthenticated``) -- any authenticated user, not
admin-only. The React shell's ``useEnabledApps`` hook consumes this to filter
its static navigation by app state. Returns the minimal projection needed for
navigation rendering; richer info (css_class, has_api_router) is reserved for
the admin listing at ``/api/admin/apps/``.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.sep.config import sep_settings
from app.sep.crud import AppStateManager
from app.sep.deps import _PROTECTED_APP_KEYS, SessionDep

router = APIRouter(tags=["apps"])


class AppKeyResponse(BaseModel):
    """Minimal per-app entry for the navigation shell.

    :param app_key: The plugin module key.
    :type app_key: str
    :param enabled: Whether the app is currently enabled.
    :type enabled: bool
    :param sidebar: Whether the plugin appears in the sidebar.
    :type sidebar: bool
    :param uri_path: The plugin's mount URI path.
    :type uri_path: str
    """

    app_key: str
    enabled: bool
    sidebar: bool
    uri_path: str


@router.get("/")
async def list_apps_for_navigation(session: SessionDep) -> list[AppKeyResponse]:
    """Return per-app state for the current user's navigation.

    Protected apps are always reported ``enabled=True``. Non-protected apps
    reflect their DB state (a missing row -> ``enabled=True``: a configured
    plugin is active until explicitly disabled).

    :param session: The database session.
    :type session: SessionDep
    :return: The per-app navigation list.
    :rtype: list[AppKeyResponse]
    """
    states = await AppStateManager.all_states(session)
    return [
        AppKeyResponse(
            app_key=(key := plugin.module_name.split(".")[-1]),
            enabled=True if key in _PROTECTED_APP_KEYS else states.get(key, True),
            sidebar=plugin.sidebar,
            uri_path=str(plugin.uri_path),
        )
        for plugin in sep_settings.PLUGINS
    ]

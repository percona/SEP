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

from app.sep.apps.framework.registry import get_app_registry
from app.sep.crud import AppStateManager
from app.sep.deps import PROTECTED_APP_KEYS, SessionDep
from app.sep.models import AppLifecycleEnum

router = APIRouter(tags=["apps"])


class AppKeyResponse(BaseModel):
    """Represent a minimal per-app entry for the navigation shell.

    :param app_key: The plugin module key.
    :type app_key: str
    :param enabled: Whether the app is currently enabled.
    :type enabled: bool
    :param sidebar: Whether the plugin appears in the sidebar.
    :type sidebar: bool
    :param uri_path: The plugin's mount URI path.
    :type uri_path: str
    :param display_name: The human-facing label for the app.
    :type display_name: str
    :param custom_ui: Whether the app ships a bespoke React UI.
    :type custom_ui: bool
    :param group: The nav group key this app nests under; ``None`` when the app
        renders as a top-level sidebar entry.
    :param nav_order: The app's sort position within the sidebar; ``None`` when
        unset.
    """

    app_key: str
    enabled: bool
    sidebar: bool
    uri_path: str
    display_name: str
    custom_ui: bool
    group: str | None
    nav_order: int | None


@router.get("/")
async def list_apps_for_navigation(session: SessionDep) -> list[AppKeyResponse]:
    """Return per-app state for the current user's navigation.

    Protected apps are always reported ``enabled=True``. Every other app reflects
    the DB state of the row governing it (a missing row -> ``enabled=True``: a
    configured plugin is active until explicitly disabled). A child app owns no
    row, so it resolves through its parent via
    :attr:`~app.sep.apps.framework.base.BaseApp.state_key`.

    :param session: The database session.
    :return: The per-app navigation list.
    """
    states = await AppStateManager.all_lifecycle_states(session)
    return [
        AppKeyResponse(
            app_key=app.key,
            enabled=app.state_key in PROTECTED_APP_KEYS
            or states.get(app.state_key, AppLifecycleEnum.ENABLED)
            == AppLifecycleEnum.ENABLED,
            sidebar=app.sidebar,
            uri_path=app.uri_path,
            display_name=app.display_name,
            custom_ui=app.custom_ui,
            group=app.group,
            nav_order=app.nav_order,
        )
        for app in get_app_registry()
    ]

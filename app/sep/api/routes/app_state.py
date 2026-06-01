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

"""Admin endpoints for managing app enable/disable state.

Mounted under ``/api/admin/apps/`` with router-level admin auth
(``IsApiAdmin``); mutations additionally require a Bearer token (CSRF defense),
both attached at the mount in :mod:`app.sep.api.router`. See
:class:`app.sep.models.AppState` for the underlying DB model and
:func:`app.sep.deps.require_app_enabled` for the per-route guard that consumes
the state at request time. Apps in :data:`app.sep.deps.PROTECTED_APP_KEYS`
cannot be toggled (toggle returns 409) and are reported with
``toggleable=False`` in the listing.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.exceptions import HTTPConflictException, HTTPNotFoundException
from app.sep.config import sep_settings
from app.sep.crud import AppStateManager
from app.sep.deps import PROTECTED_APP_KEYS, SessionDep
from app.sep.models import AppState, AppStateBase, AppStateWrite

router = APIRouter(tags=["admin", "apps"])


class AppInfoResponse(BaseModel):
    """Represent a per-app info entry returned by ``GET /``.

    :param app_key: The plugin module key.
    :type app_key: str
    :param name: The human-readable plugin name.
    :type name: str
    :param enabled: Whether the app is currently enabled.
    :type enabled: bool
    :param toggleable: Whether the app may be toggled (``False`` for protected).
    :type toggleable: bool
    :param uri_path: The plugin's mount URI path.
    :type uri_path: str
    :param css_class: The plugin's CSS class.
    :type css_class: str
    :param sidebar: Whether the plugin appears in the sidebar.
    :type sidebar: bool
    :param has_api_router: Whether the plugin exposes a JSON API router.
    :type has_api_router: bool
    """

    app_key: str
    name: str
    enabled: bool
    toggleable: bool
    uri_path: str
    css_class: str
    sidebar: bool
    has_api_router: bool


class AppStateResponse(BaseModel):
    """Represent the toggle endpoint's response.

    :param app_key: The toggled app's key.
    :type app_key: str
    :param enabled: The resulting enabled state.
    :type enabled: bool
    """

    app_key: str
    enabled: bool


@router.get("/")
async def list_apps(session: SessionDep) -> list[AppInfoResponse]:
    """List every configured app with its current enabled state.

    Returns one entry per ``SEP.PLUGINS`` entry, in declaration order. Protected
    apps (``inventory``) appear with ``enabled=True, toggleable=False``. The list
    is non-paginated: app cardinality is bounded (<20).

    :param session: The database session.
    :type session: SessionDep
    :return: The per-app info list.
    :rtype: list[AppInfoResponse]
    """
    states = await AppStateManager.all_states(session)
    return [
        AppInfoResponse(
            app_key=(key := plugin.module_name.split(".")[-1]),
            name=plugin.name,
            enabled=True if key in PROTECTED_APP_KEYS else states.get(key, True),
            toggleable=key not in PROTECTED_APP_KEYS,
            uri_path=str(plugin.uri_path),
            css_class=plugin.css_class,
            sidebar=plugin.sidebar,
            has_api_router=plugin.api_router_path is not None,
        )
        for plugin in sep_settings.PLUGINS
    ]


@router.put("/{app_key}/state", response_model=AppStateResponse)
async def update_app_state(
    app_key: str,
    body: AppStateWrite,
    session: SessionDep,
) -> AppState:
    """Toggle an app's enabled state.

    Returns 409 for protected apps (``inventory``). Returns 404 if the key does
    not match any configured plugin. A configured app with no row yet (e.g. one
    added to ``settings.yaml`` before the next startup seed) gets its row
    created with the requested state, so the toggle stays consistent with the
    read guard, which treats a missing row as enabled. Returns the updated row,
    projected through :class:`AppStateResponse` by FastAPI's ``response_model``.

    :param app_key: The app key to toggle.
    :type app_key: str
    :param body: The desired enabled state.
    :type body: AppStateWrite
    :param session: The database session.
    :type session: SessionDep
    :return: The updated app-state row.
    :rtype: AppState
    :raises HTTPConflictException: If the app is protected.
    :raises HTTPNotFoundException: If the key matches no configured plugin.
    """
    if app_key in PROTECTED_APP_KEYS:
        raise HTTPConflictException(
            detail=f"App '{app_key}' is protected and cannot be disabled.",
        )
    configured_keys = {
        plugin.module_name.split(".")[-1] for plugin in sep_settings.PLUGINS
    }
    if app_key not in configured_keys:
        raise HTTPNotFoundException(
            detail=f"No app configured with key '{app_key}'.",
        )
    state, created = await AppStateManager.get_or_create(
        session,
        AppStateBase(app_key=app_key, enabled=body.enabled),
        filter_include={"app_key"},
    )
    if created:
        return state
    return await AppStateManager.update(session, state, body)

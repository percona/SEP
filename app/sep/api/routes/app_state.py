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

from app.core.celery.deps import CeleryBeatSessionDep
from app.sep.crud import AppStateManager
from app.sep.deps import (
    PROTECTED_APP_KEYS,
    SessionDep,
    ToggleableAppKeyDep,
)
from app.sep.models import AppLifecycleEnum, AppState, AppStateBase, AppStateWrite
from app.sep.periodic_tasks import apply_effective_enabled
from app.sep.plugins.framework.registry import get_app_registry

router = APIRouter(tags=["admin", "apps"])


class AppInfoResponse(BaseModel):
    """Represent a per-app info entry returned by ``GET /``.

    :param app_key: The plugin module key.
    :type app_key: str
    :param name: The human-readable plugin name.
    :type name: str
    :param enabled: Whether the app is fully enabled (derived; deprecated).
    :type enabled: bool
    :param lifecycle_state: The app's runtime lifecycle state.
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
    lifecycle_state: AppLifecycleEnum
    toggleable: bool
    uri_path: str
    css_class: str
    sidebar: bool
    has_api_router: bool


class AppStateResponse(BaseModel):
    """Represent the toggle endpoint's response.

    :param app_key: The toggled app's key.
    :type app_key: str
    :param enabled: The resulting enabled flag (derived; deprecated).
    :type enabled: bool
    :param lifecycle_state: The resulting lifecycle state.
    """

    app_key: str
    enabled: bool
    lifecycle_state: AppLifecycleEnum


@router.get("/")
async def list_apps(session: SessionDep) -> list[AppInfoResponse]:
    """List every configured app with its current enabled state.

    Returns one entry per ``SEP.PLUGINS`` entry, in declaration order. Protected
    apps (``inventory``) and apps with no row appear as ``ENABLED`` /
    ``enabled=True, toggleable=False``. The list is non-paginated: app
    cardinality is bounded (<20).

    :param session: The database session.
    :type session: SessionDep
    :return: The per-app info list.
    :rtype: list[AppInfoResponse]
    """
    states = await AppStateManager.all_lifecycle_states(session)
    return [
        AppInfoResponse(
            app_key=app.key,
            name=app.name,
            lifecycle_state=lifecycle,
            enabled=lifecycle == AppLifecycleEnum.ENABLED,
            toggleable=app.key not in PROTECTED_APP_KEYS,
            uri_path=app.uri_path,
            css_class=app.css_class,
            sidebar=app.sidebar,
            has_api_router=app.api_router is not None,
        )
        for app in get_app_registry()
        for lifecycle in (
            AppLifecycleEnum.ENABLED
            if app.key in PROTECTED_APP_KEYS
            else states.get(app.key, AppLifecycleEnum.ENABLED),
        )
    ]


@router.put("/{app_key}/state", response_model=AppStateResponse)
async def update_app_state(
    app_key: ToggleableAppKeyDep,
    body: AppStateWrite,
    session: SessionDep,
    celery_beat_session: CeleryBeatSessionDep,
) -> AppState:
    """Transition an app to a new lifecycle state.

    Validates the requested edge against the allowed transitions
    (``ENABLED`` -> ``DISABLING``, ``DISABLED`` -> ``ENABLING``,
    ``DISABLING`` -> ``DISABLED``, ``ENABLING`` -> ``ENABLED``); an illegal edge
    returns 409. Returns 409 for protected apps (``inventory``) and 404 if the
    key does not match any configured plugin. A configured app with no row yet is
    treated as ``ENABLED`` for the gate and gets its row created with the
    requested state. Returns the updated row, projected through
    :class:`AppStateResponse` by FastAPI's ``response_model``.

    After the ``AppState`` write commits, the app's owned periodic schedules are
    re-gated via :func:`app.sep.periodic_tasks.apply_effective_enabled` so a
    non-``ENABLED`` app also stops its Celery beat tasks (and a return to
    ``ENABLED`` resumes them, subject to each schedule's ``user_enabled``
    override).

    :param app_key: The app key to transition.
    :type app_key: str
    :param body: The requested target lifecycle state.
    :type body: AppStateWrite
    :param session: The SEP database session.
    :type session: SessionDep
    :param celery_beat_session: The celery-beat database session.
    :return: The updated app-state row.
    :rtype: AppState
    :raises HTTPConflictException: When the requested transition edge is illegal.
    """
    current = await AppStateManager.current_lifecycle(session, app_key)
    AppStateManager.assert_transition_allowed(current, body.lifecycle_state)
    state, created = await AppStateManager.get_or_create(
        session,
        AppStateBase(app_key=app_key, lifecycle_state=body.lifecycle_state),
        filter_include={"app_key"},
    )
    if not created:
        state = await AppStateManager.update(session, state, body)
    await apply_effective_enabled(session, celery_beat_session, app_keys={app_key})
    return state

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

from app.celery import celery
from app.core.celery.deps import CeleryBeatSessionDep
from app.core.exceptions import HTTPConflictException
from app.sep.app_drain import finalize_drain_if_complete
from app.sep.apps.framework.registry import get_app_registry
from app.sep.crud import AppRunningTaskManager, AppStateManager
from app.sep.deps import (
    PROTECTED_APP_KEYS,
    SessionDep,
    ToggleableAppKeyDep,
)
from app.sep.models import AppLifecycleEnum, AppStateBase, AppStateWrite
from app.sep.periodic_tasks import apply_effective_enabled

router = APIRouter()


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

    Returns one entry per registered app, in declaration order (each parent is
    immediately followed by its child apps). Apps with no row default to
    ``ENABLED`` (``enabled=True``, ``toggleable=True``); protected apps
    (``inventory``) are forced to ``ENABLED`` and reported with
    ``toggleable=False``. A child app (``parent_key`` set) is not independently
    toggleable either (``toggleable=False``) and derives its lifecycle from the
    parent via :attr:`~app.sep.apps.framework.base.BaseApp.state_key`. The list is
    non-paginated: app cardinality is bounded (<20).

    :param session: The database session.
    :return: The per-app info list.
    """
    states = await AppStateManager.all_lifecycle_states(session)
    return [
        AppInfoResponse(
            app_key=app.key,
            name=app.name,
            lifecycle_state=lifecycle,
            enabled=lifecycle == AppLifecycleEnum.ENABLED,
            toggleable=app.key not in PROTECTED_APP_KEYS and app.parent_key is None,
            uri_path=app.uri_path,
            css_class=app.css_class,
            sidebar=app.sidebar,
            has_api_router=app.api_router is not None,
        )
        for app in get_app_registry()
        for lifecycle in (
            AppLifecycleEnum.ENABLED
            if app.state_key in PROTECTED_APP_KEYS
            else states.get(app.state_key, AppLifecycleEnum.ENABLED),
        )
    ]


@router.put("/{app_key:path}/state")
async def update_app_state(
    app_key: ToggleableAppKeyDep,
    body: AppStateWrite,
    session: SessionDep,
    celery_beat_session: CeleryBeatSessionDep,
) -> AppStateResponse:
    """Transition an app to a new lifecycle state.

    Validates the requested edge against the allowed transitions
    (``ENABLED`` -> ``DISABLING``, ``DISABLED`` -> ``ENABLING``,
    ``DISABLING`` -> ``DISABLED``, ``ENABLING`` -> ``ENABLED``); an illegal edge
    returns 409. Returns 409 for protected apps (``inventory``) and 404 if the
    key does not match any configured plugin. A configured app with no row yet is
    treated as ``ENABLED`` for the gate and gets its row created with the
    requested state. Returns the updated row as an :class:`AppStateResponse`
    (the return annotation drives FastAPI's response schema).

    After the ``AppState`` write commits, the app's owned periodic schedules are
    re-gated via :func:`app.sep.periodic_tasks.apply_effective_enabled` so a
    non-``ENABLED`` app also stops its Celery beat tasks (and a return to
    ``ENABLED`` resumes them, subject to each schedule's ``user_enabled``
    override).

    A ``DISABLING`` transition on an app with no in-flight tasks drains
    immediately: :func:`app.sep.app_drain.finalize_drain_if_complete` flips it
    straight to ``DISABLED`` (no ``task_postrun`` event will ever fire for an idle
    app), and the response reflects that resulting ``DISABLED`` state.

    An ``ENABLING`` transition completes synchronously: there is no warm-up to
    wait for and nothing else ever advances ``ENABLING``, so it is flipped
    straight to ``ENABLED`` (before re-gating, so the app's schedules resume in
    the same request) and the response reflects that resulting ``ENABLED`` state.

    :param app_key: The app key to transition.
    :type app_key: str
    :param body: The requested target lifecycle state.
    :type body: AppStateWrite
    :param session: The SEP database session.
    :type session: SessionDep
    :param celery_beat_session: The celery-beat database session.
    :return: The updated app-state response payload.
    :rtype: AppStateResponse
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
    resulting_state = state.lifecycle_state
    # Enabling has no warm-up to wait for (only the disable path drains in-flight
    # work), so ENABLING completes synchronously: flip it straight to ENABLED.
    # This must happen *before* the re-gate below because
    # ``apply_effective_enabled`` only re-arms an app whose state is ENABLED, and
    # nothing else (no reconciler, no task signal) ever advances ENABLING — so
    # without this the app would sit in ENABLING forever.
    if resulting_state == AppLifecycleEnum.ENABLING:
        await AppStateManager.update_where(
            session,
            {"lifecycle_state": AppLifecycleEnum.ENABLED},
            app_key=app_key,
            lifecycle_state=AppLifecycleEnum.ENABLING,
        )
        resulting_state = AppLifecycleEnum.ENABLED
    await apply_effective_enabled(session, celery_beat_session, app_keys={app_key})
    if (
        resulting_state == AppLifecycleEnum.DISABLING
        and await finalize_drain_if_complete(session, app_key)
    ):
        resulting_state = AppLifecycleEnum.DISABLED
    return AppStateResponse(
        app_key=state.app_key,
        lifecycle_state=resulting_state,
        enabled=resulting_state == AppLifecycleEnum.ENABLED,
    )


@router.post("/{app_key:path}/force-disable")
async def force_disable_app(
    app_key: ToggleableAppKeyDep,
    session: SessionDep,
) -> AppStateResponse:
    """Force a draining app straight to ``DISABLED``, terminating its tasks.

    The emergency escape hatch when a cooperative drain stalls: it terminates
    each of the app's in-flight tasks with ``revoke(..., terminate=True)``
    (SIGTERM), deletes their :class:`app.sep.models.AppRunningTask` rows, and
    transitions the app to ``DISABLED``. Requires the app to already be
    ``DISABLING`` (else 409); the default toggle path (``PUT .../state``) never
    issues a terminating revoke. No periodic re-gating is needed — the owned
    schedules were already gated off at the ``DISABLING`` write.

    :param app_key: The app to force-disable.
    :param session: The SEP database session.
    :return: The resulting ``DISABLED`` app-state response.
    :raises HTTPConflictException: When the app is not currently ``DISABLING``.
    """
    current = await AppStateManager.current_lifecycle(session, app_key)
    if current != AppLifecycleEnum.DISABLING:
        raise HTTPConflictException(
            detail=f"App '{app_key}' is not draining (state {current}); "
            "force-disable only applies to a DISABLING app.",
        )
    running = await AppRunningTaskManager.list(session, app_key=app_key)
    for task in running:
        celery.control.revoke(task.celery_task_id, terminate=True)
    await AppRunningTaskManager.delete_where(session, app_key=app_key)
    await AppStateManager.update_where(
        session,
        {"lifecycle_state": AppLifecycleEnum.DISABLED},
        app_key=app_key,
    )
    return AppStateResponse(
        app_key=app_key,
        lifecycle_state=AppLifecycleEnum.DISABLED,
        enabled=False,
    )

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

"""Wire SEP's DB-backed settings overrides into the web and worker processes.

Holds the single composition of the SEP-side proxy registry, so every SEP
process refreshes the same set and a class added here reaches all of them at
once rather than only the one whose wiring was remembered.

This module is named directly in ``STATIC_CELERY_INCLUDE`` so its signal
receivers register at worker startup even in an image that ships no app with a
``celery.py``. It registers no Celery task, so it never appears in
``celery.tasks``.
"""

from collections.abc import Mapping
from typing import Any

from celery.signals import worker_process_init, worker_process_shutdown
from sqlmodel.ext.asyncio.session import AsyncSession

from app.celery import celery
from app.core.alerts.config import alert_settings, AlertSettings
from app.core.config import Settings, settings
from app.core.settings_override.lifecycle import (
    CallbackRegistry,
    ProxyEntry,
    ProxyRegistry,
    publish_snapshot,
)
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.worker import WorkerRefresher
from app.sep.apps.framework.registry import collect_app_owned_settings_classes
from app.sep.config import sep_settings, SEPSettings
from app.sep.db import get_async_session_maker
from app.sep.middleware.messages.config import messages_settings, MessagesSettings
from app.sep.snippets.config import snippets_settings, SnippetsSettings


def build_sep_override_proxies() -> ProxyRegistry:
    """Compose the SEP-side proxy registry: app-owned entries plus SEP's own.

    SEP's own entries override whatever the activated apps declare,
    so ``SETTINGS`` and ``ALERT_SETTINGS`` -- shared module-level proxies
    (``settings`` / ``alert_settings``) -- keep the SEP refresher as their sole
    owner even if an app were to declare them: under the combined
    ``app.main:app`` the Tasks refresher must not also publish into them from
    the Tasks database.

    ``collect_app_owned_settings_classes`` imports every activated app module,
    so this runs at call time, never at import: this module is itself named in
    ``STATIC_CELERY_INCLUDE``, so reaching the app tree at its module scope
    would import every activated app during include-import, alongside the app
    ``celery.py`` modules being imported from the same list.

    :return: The wired proxy registry keyed by class identifier.
    :raises TypeError: Propagates from ``collect_app_owned_settings_classes``
        when an app's ``APP_OWNED_SETTINGS_CLASSES`` declaration is malformed.
    :raises ValueError: Propagates from ``collect_app_owned_settings_classes``
        when two apps declare the same class, or one references an unknown app
        key.
    """
    proxies = {
        entry.setting_class: ProxyEntry(entry.proxy, entry.settings_cls)
        for entry in collect_app_owned_settings_classes()
    }
    proxies.update(
        {
            SettingClassEnum.SEP_SETTINGS: ProxyEntry(sep_settings, SEPSettings),
            SettingClassEnum.SNIPPETS_SETTINGS: ProxyEntry(
                snippets_settings, SnippetsSettings
            ),
            SettingClassEnum.MESSAGES_SETTINGS: ProxyEntry(
                messages_settings, MessagesSettings
            ),
            SettingClassEnum.SETTINGS: ProxyEntry(settings, Settings),
            SettingClassEnum.ALERT_SETTINGS: ProxyEntry(alert_settings, AlertSettings),
        }
    )
    return proxies


async def republish_sep_settings_snapshot(session: AsyncSession) -> None:
    """Republish the SEP settings snapshot from a session already in hand.

    Let a Celery task decide against the overrides currently stored, not only
    those present when its child last refreshed: the worker's refresher advances
    only while something drives ``celery.loop``, so a child can hold a pre-write
    snapshot for an unbounded time, while an awaited republish inside a task
    body is driven by the same ``run_until_complete`` that drives the task.

    Only ``SEP_SETTINGS`` is republished, and no rebind callback fires:
    ``publish_snapshot`` has no callback channel. That is harmless for a worker
    caller, whose ``WORKER_OVERRIDE_CALLBACKS`` watches ``SETTINGS`` alone. It
    would not be for a web-process caller: ``sep_overrides_lifespan`` registers
    ``SEP_SETTINGS`` rebinders for ``INVENTORY_ENDPOINT``, ``TASKS_ENDPOINT``
    and ``APP_DRAIN``, and republishing here leaves the periodic refresher an
    empty diff, so those rebinds would silently never fire.

    :param session: A session bound to the SEP database, used to read the
        override rows.
    :raises Exception: Propagates whatever ``publish_snapshot`` raises, in
        practice ``SQLAlchemyError`` from the override-row query. There is no
        per-proxy handler here as there is in ``refresh_all``; the caller owns
        the failure.
    """
    await publish_snapshot(sep_settings, session, SEPSettings)


async def invalidate_pmm_clients(_: Mapping[str, object]) -> None:
    """Evict the cached PMM client on the current endpoint after a ``PMM`` override.

    A same-endpoint change (credentials, SSL) evicts the now-stale client so the
    next :class:`PMMSyncer` key-misses to a fresh one via its ``default_factory``
    PMM read. Known limitation: an endpoint change leaves the client keyed by the
    old endpoint cached until ``close_all`` closes it at shutdown; syncers key on
    the new endpoint, so nothing reads it in the meantime.

    :param _: The new effective ``Settings`` snapshot mapping (unused -- the
        current PMM endpoint is re-read from the proxy).
    """
    endpoint = settings.PMM.endpoint
    if endpoint is not None:
        await settings.invalidate_client(str(endpoint))


#: The callbacks the worker refresher registers -- deliberately a strict subset
#: of the web lifespan's registry. The dropped entries either rebind ``app.state``
#: clients or reseed beat-schedule rows, neither of which a worker child owns.
#: ``invalidate_pmm_clients`` is kept because ``ClientRegistry.IMMUTABLE_KEYS``
#: excludes ``api_key``: a same-endpoint credential override would otherwise
#: refresh the snapshot while worker tasks keep the client with the old key.
WORKER_OVERRIDE_CALLBACKS: CallbackRegistry = {
    (SettingClassEnum.SETTINGS, "PMM"): invalidate_pmm_clients,
}


_refresher = WorkerRefresher(
    lambda: celery.loop,
    lambda: get_async_session_maker(),
    build_sep_override_proxies,
)


@worker_process_init.connect
def start_sep_settings_override_refresher(**_: Any) -> None:
    """Start the worker's SEP-side DB-backed settings-override refresher.

    A second refresher alongside the Tasks-side one in :mod:`app.tasks.celery`:
    the two proxy sets resolve against different databases and ``refresh_all``
    opens one session per call, so one refresher serves exactly one database.
    Periodic progress is best-effort, advancing only while a task drives
    ``celery.loop.run_until_complete``; the initial inline refresh still seeds
    the snapshot before this handler returns, bounded by a fraction of
    ``celery.conf.worker_proc_alive_timeout`` so a hanging database cannot
    push the child past the prefork pool's liveness deadline. On seed expiry
    the periodic refresher still starts and the child runs with env-only
    overrides until a later cycle lands.

    ``messages_settings._resolve()`` runs unconditionally for validation even
    when the refresher is disabled, as ``sep_overrides_lifespan`` does. The two
    differ in consequence: the lifespan's call aborts startup, while Celery
    catches and logs whatever a signal receiver raises, so an invalid config
    here leaves the child running without this refresher.

    :raises ValidationError: Propagates from ``messages_settings._resolve()``
        when the messages config is invalid. Celery logs it and carries on
        dispatching; the child starts without this refresher.
    :raises Exception: Propagates whatever composing the proxy registry or the
        initial inline refresh raises -- a malformed app-owned declaration
        (``TypeError`` / ``ValueError``) or a session-maker failure -- and is
        absorbed the same way. Per-proxy refresh failures and a bounded-seed
        expiry are caught and logged inside the refresher; the latter still
        starts the periodic task.
    """
    messages_settings._resolve()  # noqa: SLF001
    _refresher.start(
        callbacks=WORKER_OVERRIDE_CALLBACKS,
        proc_alive_timeout=celery.conf.worker_proc_alive_timeout,
    )


@worker_process_shutdown.connect
def stop_sep_settings_override_refresher(**_: Any) -> None:
    """Stop and drain the worker's SEP-side refresher on shutdown.

    A no-op when the refresher never started (disabled, or shutdown fired before
    init).
    """
    _refresher.stop()

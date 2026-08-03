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

from app.celery import celery
from app.core.alerts.config import alert_settings, AlertSettings
from app.core.config import Settings, settings
from app.core.settings_override.lifecycle import (
    CallbackRegistry,
    ProxyEntry,
    ProxyRegistry,
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

    SEP's own entries are applied **over** whatever the activated apps declare,
    so ``SETTINGS`` and ``ALERT_SETTINGS`` -- shared module-level proxies
    (``settings`` / ``alert_settings``) -- keep the SEP refresher as their sole
    owner even if an app were to declare them: under the combined
    ``app.main:app`` the Tasks refresher must not also publish into them from
    the Tasks database.

    ``collect_app_owned_settings_classes`` imports every activated app module,
    so this runs at call time, never at import: an import-time edge into
    ``app.sep.apps.<app>`` from outside that tree breaks the import boundary and
    the side-car image, which strips non-activated app packages.

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


async def invalidate_pmm_clients(_: Mapping[str, object]) -> None:
    """Evict the cached PMM client on the current endpoint after a ``PMM`` override.

    A same-endpoint change (credentials, SSL) evicts the now-stale client so the
    next :class:`PMMSyncer` key-misses to a fresh one via its ``default_factory``
    PMM read. Known limitation: when the PMM *endpoint itself* changes, the client
    keyed by the **old** endpoint is not evicted here (this callback only sees the
    new endpoint); it is harmless -- new syncers key-miss to a fresh client on the
    new endpoint -- and the old client is closed at shutdown via ``close_all``.

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
    the snapshot before this handler returns.

    ``messages_settings._resolve()`` runs unconditionally for fail-fast
    validation even when the refresher is disabled, mirroring
    ``sep_overrides_lifespan``.

    :raises ValidationError: Propagates from ``messages_settings._resolve()``
        when the messages config is invalid, failing child start loudly.
    :raises Exception: Propagates whatever composing the proxy registry or the
        initial inline refresh raises -- a malformed app-owned declaration
        (``TypeError`` / ``ValueError``) or a session-maker failure. Per-proxy
        refresh failures are caught and logged inside ``refresh_all``.
    """
    messages_settings._resolve()  # noqa: SLF001
    _refresher.start(
        settings.SETTINGS_OVERRIDE_REFRESH_INTERVAL,
        enabled=settings.SETTINGS_OVERRIDE_REFRESHER_ENABLED,
        callbacks=WORKER_OVERRIDE_CALLBACKS,
    )


@worker_process_shutdown.connect
def stop_sep_settings_override_refresher(**_: Any) -> None:
    """Stop and drain the worker's SEP-side refresher on shutdown.

    A no-op when the refresher never started (disabled, or shutdown fired before
    init).
    """
    _refresher.stop()

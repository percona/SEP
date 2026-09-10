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

import logging.config
from collections.abc import Mapping
from copy import deepcopy
from typing import Any, cast

from celery.signals import worker_process_init, worker_process_shutdown
from sqlmodel.ext.asyncio.session import AsyncSession

from app.celery import celery
from app.core.alerts.config import alert_settings, AlertSettings
from app.core.config import PMMSettings, Settings, settings
from app.core.settings_override.lifecycle import (
    CallbackRegistry,
    previous_or_base,
    ProxyEntry,
    ProxyRegistry,
    publish_snapshot,
    SnapshotChange,
)
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.worker import WorkerRefresher
from app.sep.apps.framework.registry import collect_app_owned_settings_classes
from app.sep.config import sep_settings, SEPSettings
from app.sep.db import get_async_session_maker
from app.sep.snippets.config import snippets_settings, SnippetsSettings

logger = logging.getLogger(__name__)


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
        when an activated app's declaration is invalid; that function
        enumerates the cases.
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


async def invalidate_pmm_clients(change: SnapshotChange) -> None:
    """Evict cached PMM clients on the previous and current endpoints after a ``PMM`` override.

    Evicts the ordered de-duplicated set of previous-and-current endpoints so a
    same-endpoint change (credentials, SSL) collapses to a single eviction, while
    an endpoint change also drops the client keyed by the endpoint no longer in
    use. The next :class:`PMMSyncer` key-misses to a fresh client via its
    ``default_factory`` PMM read. When ``PMM`` is absent from ``change.previous``
    (override created), :func:`previous_or_base` supplies the YAML/env value.

    :param change: The override snapshots on either side of the republish.
    """
    previous_pmm = cast(PMMSettings, previous_or_base(change, settings, "PMM"))
    for endpoint in dict.fromkeys(
        str(pmm.endpoint)
        for pmm in (previous_pmm, settings.PMM)
        if pmm.endpoint is not None
    ):
        await settings.invalidate_client(endpoint)


async def apply_logging_dictconfig(_: Mapping[str, object]) -> None:
    """Re-apply ``logging.config.dictConfig`` after a global ``LOGGING`` override.

    ``LOGGING`` is a HOT field, but ``LOGGING_CONFIG`` (the dict handed to
    ``dictConfig``) is not: the override snapshot replaces only the ``LOGGING``
    key, so ``settings.LOGGING_CONFIG`` still carries the level baked in by the
    ``set_log_level`` model validator at construction time. This callback mirrors
    that validator -- inject the now-live ``settings.LOGGING`` into a copy of the
    config and re-apply it -- so a log-level change takes effect in the SEP web
    process and Celery worker children without a restart. Failures are logged and
    swallowed: a malformed config must not take the process down mid-request or
    mid-task. ``LOGGING_CONFIG`` sets ``disable_existing_loggers: False``, so
    re-entering ``dictConfig`` from a worker refresh cycle leaves the loggers
    Celery created at runtime enabled, and re-creates the ones the config names
    -- ``celery`` among them -- with their handlers.

    :param _: The new effective ``Settings`` snapshot mapping (unused -- the level
        is re-read from the proxy).
    """
    try:
        config = deepcopy(settings.LOGGING_CONFIG)
        config["loggers"][""]["level"] = settings.LOGGING
        config["loggers"]["app"]["level"] = settings.LOGGING
        logging.config.dictConfig(config)
    except Exception:
        logger.exception("Failed to re-apply logging config after LOGGING override")


#: The callbacks the worker refresher registers -- deliberately a strict subset
#: of the web lifespan's registry. The dropped entries either rebind ``app.state``
#: clients or reseed beat-schedule rows, neither of which a worker child owns.
#: ``invalidate_pmm_clients`` is kept because ``ClientRegistry.IMMUTABLE_KEYS``
#: excludes ``api_key``: a same-endpoint credential override would otherwise
#: refresh the snapshot while worker tasks keep the client with the old key.
#: ``apply_logging_dictconfig`` is kept so a HOT ``LOGGING`` override re-enters
#: ``dictConfig`` after Celery's ``setup_logging`` installed boot-time levels.
WORKER_OVERRIDE_CALLBACKS: CallbackRegistry = {
    (SettingClassEnum.SETTINGS, "PMM"): invalidate_pmm_clients,
    (SettingClassEnum.SETTINGS, "LOGGING"): apply_logging_dictconfig,
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

    :raises Exception: Propagates whatever composing the proxy registry or the
        initial inline refresh raises -- a malformed app-owned declaration
        (``TypeError`` / ``ValueError``) or a session-maker failure -- and is
        absorbed the same way. Per-proxy refresh failures and a bounded-seed
        expiry are caught and logged inside the refresher; the latter still
        starts the periodic task.
    """
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

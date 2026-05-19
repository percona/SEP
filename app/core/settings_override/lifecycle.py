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

"""Async refresher that periodically reloads override snapshots from the DB."""

__all__ = ["ProxyEntry", "ProxyRegistry", "refresh_all", "start_refresh_task"]

import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import NamedTuple

from pydantic import BaseModel
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.settings_override.cache import build_snapshot
from app.core.settings_override.models import SettingClassEnum
from app.core.settings_override.proxy import OverridableSettingsProxy

logger = logging.getLogger(__name__)

SessionMakerFactory = Callable[[], async_sessionmaker]


class ProxyEntry(NamedTuple):
    """Pair a wired proxy with the Pydantic class it wraps.

    :param proxy: The overridable proxy instance whose snapshot to refresh.
    :type proxy: OverridableSettingsProxy
    :param settings_cls: The Pydantic settings class wrapped by ``proxy``.
        Used to look up field metadata when building the snapshot.
    :type settings_cls: type[BaseModel]
    """

    proxy: OverridableSettingsProxy
    settings_cls: type[BaseModel]


ProxyRegistry = dict[SettingClassEnum, ProxyEntry]


async def refresh_all(
    session_maker_factory: SessionMakerFactory,
    proxies: ProxyRegistry,
) -> None:
    """Refresh override snapshots for all wired proxies in a single session.

    Per-proxy failures (raised from :func:`build_snapshot` once a session is
    open) are caught and logged: the previous snapshot is retained for that
    proxy and the rest of ``proxies`` continue to refresh. Failures that
    occur *before* per-proxy iteration begins -- specifically from
    ``session_maker_factory()`` or ``async_session_maker()`` -- are NOT
    handled here; they propagate to the caller. The background refresher
    in :func:`start_refresh_task` wraps its periodic invocation in a broad
    ``except`` so transient engine/pool errors do not kill the task.

    :param session_maker_factory: A zero-argument callable returning a
        service-scoped ``async_sessionmaker``. Invoked exactly once per call
        to avoid recreating session makers on each iteration.
    :type session_maker_factory: SessionMakerFactory
    :param proxies: The wired proxy registry keyed by class identifier.
    :type proxies: ProxyRegistry
    :raises Exception: Re-raises any failure from ``session_maker_factory()``
        or from opening the ``async_session_maker()`` context (engine not
        reachable, pool exhausted, auth, ...). Per-proxy ``build_snapshot``
        failures are handled inline and do NOT propagate.
    """
    async_session_maker = session_maker_factory()
    async with async_session_maker() as session:
        for setting_class, entry in proxies.items():
            try:
                snapshot = await build_snapshot(
                    session, entry.settings_cls, setting_class
                )
            except Exception:
                logger.exception(
                    "Failed to refresh overrides for %s; keeping previous snapshot",
                    setting_class.value,
                )
                continue
            # ``_set_snapshot`` is the intentional refresher-only entry point
            # for swapping the proxy's snapshot; see its docstring. The
            # SLF001 silence is local to this caller, not a per-file blanket.
            entry.proxy._set_snapshot(snapshot)  # noqa: SLF001


async def start_refresh_task(
    session_maker_factory: SessionMakerFactory,
    proxies: ProxyRegistry,
    interval: timedelta,
) -> asyncio.Task:
    """Perform an initial refresh and start a background refresh loop.

    The initial refresh awaits inline so the lifespan does not yield until
    the first snapshot has been observed. Subsequent refreshes run inside an
    :func:`asyncio.create_task` that sleeps for ``interval`` between cycles.

    :param session_maker_factory: A zero-argument callable returning a
        service-scoped ``async_sessionmaker``.
    :type session_maker_factory: SessionMakerFactory
    :param proxies: The wired proxy registry keyed by class identifier.
    :type proxies: ProxyRegistry
    :param interval: The wall-clock delay between refresh cycles. Must be a
        positive duration; the :class:`Settings` field validator enforces
        this at construction time.
    :type interval: timedelta
    :return: The background refresh task. Callers must cancel and await this
        task during shutdown to drain pending iterations cleanly.
    :rtype: asyncio.Task
    :raises Exception: Re-raises any failure from the inline initial
        :func:`refresh_all` call -- typically a ``session_maker_factory()``
        or session-open failure (see :func:`refresh_all`). Subsequent
        iterations inside the background task are wrapped in ``except`` and
        do NOT propagate; only the startup-time refresh can break the
        lifespan.
    """
    await refresh_all(session_maker_factory, proxies)
    interval_seconds = interval.total_seconds()

    async def _loop() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await refresh_all(session_maker_factory, proxies)
            except Exception:
                logger.exception(
                    "Settings override refresher iteration failed; will retry next cycle"
                )

    return asyncio.create_task(_loop(), name="settings-override-refresher")

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

__all__ = [
    "ProxyEntry",
    "ProxyRegistry",
    "refresh_all",
    "settings_override_refresher",
    "start_refresh_task",
]

import asyncio
import logging
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager, suppress
from datetime import timedelta
from typing import NamedTuple

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.config import BaseYamlSettings
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
    :type settings_cls: type[BaseYamlSettings]
    """

    proxy: OverridableSettingsProxy
    settings_cls: type[BaseYamlSettings]


ProxyRegistry = dict[SettingClassEnum, ProxyEntry]


async def refresh_all(
    session_maker_factory: SessionMakerFactory,
    proxies: ProxyRegistry,
) -> None:
    """Refresh override snapshots for all wired proxies in a single session.

    Per-proxy failures (raised from :func:`build_snapshot` once a session is
    open) are caught and logged: the previous snapshot is retained for that
    proxy and the rest of ``proxies`` continue to refresh. The session is
    rolled back after each failure so that on Postgres -- where a failed
    query leaves the transaction in ``InFailedSqlTransaction`` state until
    explicit rollback -- the next proxy's ``manager.list(...)`` does not
    inherit the aborted transaction. Failures that occur *before* per-proxy
    iteration begins -- specifically from ``session_maker_factory()`` or
    ``async_session_maker()`` -- are NOT handled here; they propagate to the
    caller. The background refresher in :func:`start_refresh_task` wraps its
    periodic invocation in a broad ``except`` so transient engine/pool
    errors do not kill the task.

    :param session_maker_factory: A zero-argument callable returning a
        service-scoped ``async_sessionmaker``. Invoked exactly once per call
        to avoid recreating session makers on each iteration.
    :type session_maker_factory: SessionMakerFactory
    :param proxies: The wired proxy registry keyed by class identifier.
    :type proxies: ProxyRegistry
    :raises Exception: Re-raises any failure from
        ``session_maker_factory()`` itself (e.g. the factory is misconfigured
        or its engine cannot be constructed). Connection-time failures
        against the DB -- engine unreachable, pool exhausted, auth -- do not
        surface here because ``async_session_maker()`` does not check out a
        connection; those errors fire later inside ``build_snapshot()`` and
        are caught by the per-proxy handler.
    """
    async_session_maker = session_maker_factory()
    async with async_session_maker() as session:
        for setting_class, entry in proxies.items():
            try:
                snapshot = await build_snapshot(session, entry.settings_cls)
            except Exception:
                logger.exception(
                    "Failed to refresh overrides for %s; keeping previous snapshot",
                    setting_class.name,
                )
                # Roll back so a Postgres ``InFailedSqlTransaction`` from this
                # proxy does not cascade into every subsequent proxy's
                # ``manager.list(...)`` on the shared session.
                await session.rollback()
                continue
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
        :func:`refresh_all` call -- in practice limited to
        ``session_maker_factory()`` failures (see :func:`refresh_all` for the
        narrowed contract). Connection-time DB failures from the initial
        snapshot build are caught per-proxy and do NOT propagate.
        Subsequent iterations inside the background task are also wrapped in
        ``except`` and do NOT propagate; only ``session_maker_factory()``
        failures at startup can break the lifespan.
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


@asynccontextmanager
async def settings_override_refresher(
    session_maker_factory: SessionMakerFactory,
    proxies: ProxyRegistry,
    interval: timedelta,
    *,
    enabled: bool,
) -> AsyncGenerator[None, None]:
    """Run the background override refresher for the duration of a lifespan.

    Start the periodic refresher on enter (when ``enabled``), then cancel and
    drain it on exit. When ``enabled`` is ``False`` the context manager is a
    no-op and no refresh task is created -- the wrapped block still runs.

    :param session_maker_factory: A zero-argument callable returning a
        service-scoped ``async_sessionmaker``, forwarded to
        :func:`start_refresh_task`.
    :type session_maker_factory: SessionMakerFactory
    :param proxies: The wired proxy registry keyed by class identifier.
    :type proxies: ProxyRegistry
    :param interval: The wall-clock delay between refresh cycles.
    :type interval: timedelta
    :param enabled: Whether to start the background refresher. When ``False``,
        the context manager yields without creating a task.
    :type enabled: bool
    :yield: None
    :rtype: AsyncGenerator[None, None]
    """
    refresher: asyncio.Task | None = None
    if enabled:
        refresher = await start_refresh_task(session_maker_factory, proxies, interval)
    try:
        yield
    finally:
        if refresher is not None:
            refresher.cancel()
            with suppress(asyncio.CancelledError):
                await refresher

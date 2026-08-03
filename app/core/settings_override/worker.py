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

"""Own a Celery prefork child's settings-override refresher task."""

from __future__ import annotations

__all__ = ["WorkerRefresher"]

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

from app.core.settings_override.lifecycle import start_refresh_task

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from app.core.settings_override.lifecycle import (
        CallbackRegistry,
        ProxyRegistry,
        SessionMakerFactory,
    )


class WorkerRefresher:
    """Own one prefork child's settings-override refresher task.

    Hold the lifecycle boilerplate every worker-side refresher needs -- the
    enabled gate, the idempotent already-running early-return, the initial
    inline refresh, and the cancel-and-drain on shutdown -- so each service
    module only supplies its own event loop, session maker and proxy set.

    Every dependency is a zero-argument callable resolved at :meth:`start`
    time, never a value captured at construction: the instance is a
    module-level singleton built at import, while the event loop is recreated
    per prefork child and the session maker is rebound in tests.

    ``interval`` and ``enabled`` are :meth:`start` parameters rather than reads
    of ``app.core.config.settings`` because this package must not import that
    module at runtime -- ``Settings`` is itself built from
    :mod:`app.core.settings_override.proxy`.

    :param loop_getter: Returns the event loop that drives the refresh task.
    :param session_maker_factory: Returns the service-scoped
        ``async_sessionmaker`` the refresh cycle reads override rows through.
    :param proxies_factory: Composes the proxy registry to refresh, invoked
        once per effective :meth:`start`.
    """

    def __init__(
        self,
        loop_getter: Callable[[], asyncio.AbstractEventLoop],
        session_maker_factory: SessionMakerFactory,
        proxies_factory: Callable[[], ProxyRegistry],
    ) -> None:
        self._loop_getter = loop_getter
        self._session_maker_factory = session_maker_factory
        self._proxies_factory = proxies_factory
        self.task: asyncio.Task | None = None

    def start(
        self,
        interval: timedelta,
        *,
        enabled: bool,
        callbacks: CallbackRegistry | None = None,
    ) -> None:
        """Start this child's refresher, unless disabled or already running.

        The initial refresh inside :func:`start_refresh_task` awaits inline, so
        the snapshot is seeded before this method returns; periodic progress
        thereafter advances only while something drives the loop.

        :param interval: The wall-clock delay between refresh cycles.
        :param enabled: Whether to start a refresher at all. When ``False``
            nothing is resolved -- neither the proxy registry nor the session
            maker -- and no task is created.
        :param callbacks: Optional rebind callbacks fired by the periodic loop
            when a watched override changes value.
        :raises Exception: Re-raises whatever ``proxies_factory()`` raises --
            it is evaluated before the refresh starts -- and whatever the
            initial inline refresh propagates, in practice limited to
            ``session_maker_factory()`` failures. Per-proxy refresh failures
            are caught and logged inside ``refresh_all``.
        """
        if not enabled:
            return
        if self.task is not None and not self.task.done():
            return
        self.task = self._loop_getter().run_until_complete(
            start_refresh_task(
                self._session_maker_factory,
                self._proxies_factory(),
                interval,
                callbacks,
            )
        )

    def stop(self) -> None:
        """Cancel and drain this child's refresher; a no-op when never started."""
        if self.task is None:
            return
        self.task.cancel()
        with suppress(asyncio.CancelledError):
            self._loop_getter().run_until_complete(self.task)
        self.task = None

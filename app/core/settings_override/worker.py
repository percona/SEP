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

"""Own a Celery prefork child's settings-override boundary refresher."""

from __future__ import annotations

__all__ = ["SEED_TIMEOUT_FRACTION", "WorkerRefresher"]

import asyncio
import logging
import time
from typing import TYPE_CHECKING

from app.core.settings_override.lifecycle import (
    bounded_seed,
    refresh_all,
    resolve_refresher_options,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import timedelta

    from app.core.settings_override.lifecycle import (
        CallbackRegistry,
        ProxyRegistry,
        SessionMakerFactory,
    )

logger = logging.getLogger(__name__)

#: Fraction of the prefork pool's child-liveness deadline the inline seed may
#: consume. Strictly below 1.0: ``process_initializer`` does more than the
#: seed, and the child must still send ``WORKER_UP`` inside the same window.
SEED_TIMEOUT_FRACTION = 0.5


class WorkerRefresher:
    """Own one prefork child's settings-override boundary refresher.

    Hold the lifecycle boilerplate every worker-side refresher needs -- the
    enabled gate, the idempotent already-armed early-return, the initial
    inline seed, and disarm on shutdown -- so each service module only
    supplies its own event loop, session maker and proxy set. After
    :meth:`start`, refreshes are pulled from ``task_prerun`` via
    :meth:`maybe_refresh` rather than driven by a background
    ``asyncio.sleep`` loop: a prefork child's loop only runs inside
    ``run_until_complete`` windows, so a timer-based cycle could starve.

    Every dependency is a zero-argument callable resolved at :meth:`start`
    time, never a value captured at construction: the instance is a
    module-level singleton built at import, while the event loop is recreated
    per prefork child and the session maker is rebound in tests. The
    last-refresh timestamp is likewise per-child after the fork.

    ``interval``, ``enabled`` and ``proc_alive_timeout`` are :meth:`start`
    parameters rather than reads of ``app.core.config.settings`` because the
    override substrate must not import that module at runtime -- ``Settings``
    is itself built from :mod:`app.core.settings_override.proxy`.

    :param loop_getter: Returns the event loop that drives the seed and
        boundary refreshes.
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
        self._interval_seconds: float = 0.0
        self._armed: bool = False
        self._last_refresh: float = 0.0
        self._proxies: ProxyRegistry | None = None
        self._callbacks: CallbackRegistry | None = None

    def start(
        self,
        interval: timedelta | None = None,
        *,
        enabled: bool | None = None,
        callbacks: CallbackRegistry | None = None,
        proc_alive_timeout: float | None = None,
    ) -> None:
        """Seed this child's overrides and arm boundary refresh, unless disabled.

        The initial refresh awaits inline so the snapshot is seeded before this
        method returns. No periodic ``asyncio.Task`` is created: subsequent
        refreshes are pulled from :meth:`maybe_refresh` at task boundaries.

        When ``proc_alive_timeout`` is set, the inline seed is bounded to
        :data:`SEED_TIMEOUT_FRACTION` of that deadline via
        :func:`~app.core.settings_override.lifecycle.bounded_seed` so a hanging
        database cannot push the child past the prefork pool's liveness window.
        On seed-budget expiry the child is still armed -- the next due
        ``task_prerun`` will refresh -- and starts with unseeded (env-only)
        overrides until then.

        :param interval: Minimum delay between boundary refreshes. ``None``,
            the default, reads
            ``Settings.SETTINGS_OVERRIDE.REFRESH_INTERVAL``.
        :param enabled: Whether to arm a refresher at all. When ``False``
            nothing is resolved (neither the proxy registry nor the session
            maker) and the child stays disarmed. ``None``, the default, reads
            ``Settings.SETTINGS_OVERRIDE.REFRESHER_ENABLED``.
        :param callbacks: Optional rebind callbacks fired by a boundary
            :func:`~app.core.settings_override.lifecycle.refresh_all` when a
            watched override changes value. Not applied to the inline seed.
        :param proc_alive_timeout: The prefork pool's child-liveness deadline
            in seconds. ``None`` (the default) leaves the inline seed
            unbounded.
        :raises Exception: Re-raises whatever ``proxies_factory()`` raises --
            it is evaluated before the refresh starts -- and whatever an
            unbounded seed propagates, in practice limited to
            ``session_maker_factory()`` failures. Per-proxy refresh failures
            are caught and logged inside ``refresh_all``. A bounded-seed
            expiry is caught inside :func:`~app.core.settings_override.lifecycle.bounded_seed`
            and does not propagate; the child is still armed.
        """
        interval, enabled = resolve_refresher_options(interval, enabled=enabled)
        if not enabled:
            return
        if self._armed:
            return
        proxies = self._proxies_factory()
        seed_timeout = (
            None
            if proc_alive_timeout is None
            else proc_alive_timeout * SEED_TIMEOUT_FRACTION
        )
        loop = self._loop_getter()
        if seed_timeout is None:
            loop.run_until_complete(refresh_all(self._session_maker_factory, proxies))
            self._last_refresh = time.monotonic()
        else:
            seeded = loop.run_until_complete(
                bounded_seed(self._session_maker_factory, proxies, seed_timeout)
            )
            # A completed seed starts the interval clock; an expired seed leaves
            # the stamp at 0.0 so the next task boundary is immediately due.
            self._last_refresh = time.monotonic() if seeded else 0.0
        self._interval_seconds = interval.total_seconds()
        self._proxies = proxies
        self._callbacks = callbacks
        self._armed = True

    def maybe_refresh(self) -> None:
        """Refresh overrides when armed and the interval has elapsed.

        Intended for ``task_prerun`` receivers. The due-check is a monotonic
        comparison with no I/O: tasks arriving inside the interval no-op.
        When due, ``refresh_all`` runs to completion inside a single
        ``run_until_complete`` window, bounded by the refresh interval itself.
        Budget expiry logs once at WARNING; any other failure is logged and
        swallowed. Neither case fails or aborts the task that triggered the
        refresh -- the previous snapshot stays in effect. The interval stamp
        advances on every attempted due refresh so a failing cycle cannot
        hammer the database on every subsequent dispatch.
        """
        if not self._armed or self._proxies is None:
            return
        now = time.monotonic()
        if now - self._last_refresh < self._interval_seconds:
            return
        try:
            self._loop_getter().run_until_complete(
                asyncio.wait_for(
                    refresh_all(
                        self._session_maker_factory,
                        self._proxies,
                        self._callbacks,
                    ),
                    timeout=self._interval_seconds,
                )
            )
        except TimeoutError:
            logger.warning(
                "Settings-override boundary refresh exceeded its %.2fs budget; "
                "keeping previous snapshot",
                self._interval_seconds,
            )
        except Exception:
            logger.exception(
                "Settings-override boundary refresh failed; keeping previous snapshot"
            )
        finally:
            self._last_refresh = time.monotonic()

    def stop(self) -> None:
        """Disarm this child's refresher; a no-op when never started.

        After disarm, :meth:`maybe_refresh` no-ops so a shut-down child
        performs no further boundary refresh. There is no periodic task to
        cancel.
        """
        self._armed = False
        self._proxies = None
        self._callbacks = None

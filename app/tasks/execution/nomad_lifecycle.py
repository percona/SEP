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

"""Own the entered NomadExecutor and rebind it when its override changes."""

__all__ = ["NomadLifecycle", "normalize_nomad_config_value"]

import asyncio
import logging
from collections.abc import Mapping
from typing import Any, Self

from fastapi import FastAPI

from app.core.utils.fields import PRESERVE_CREDENTIALS_CONTEXT
from app.tasks.config import tasks_settings
from app.tasks.execution.executors.nomad import NomadExecutor

logger = logging.getLogger(__name__)


def normalize_nomad_config_value(value: object) -> NomadExecutor:
    """Reconstruct a :class:`NomadExecutor` from a fingerprint mapping.

    The override snapshot intentionally stores ``NOMAD`` as a plain config
    fingerprint (a ``dict``) rather than a live executor, so two snapshots
    built from the same override compare equal -- a live instance with a
    per-instance ``ContextVar`` private attribute never would. A request-less
    reader that only drives the config-built sync ``self.backend`` sub-client
    needs a usable :class:`NomadExecutor` *instance*, not the dict; an
    un-entered instance is sufficient because those readers never touch the
    live aiohttp session.

    :param value: Either a live :class:`NomadExecutor` (no override active, the
        snapshot fell through to the YAML value) or a fingerprint mapping (an
        override is active).
    :type value: object
    :return: The value itself when already a :class:`NomadExecutor`, otherwise
        a freshly-validated (un-entered) executor built from the mapping.
    :rtype: NomadExecutor
    :raises ValidationError: If ``value`` is a mapping that does not describe a
        valid :class:`NomadExecutor`.
    :raises TypeError: If ``value`` is neither a :class:`NomadExecutor` nor a
        mapping.
    """
    if isinstance(value, NomadExecutor):
        return value
    if isinstance(value, Mapping):
        return NomadExecutor.model_validate(value)
    raise TypeError(f"Cannot normalize {type(value).__name__} to a NomadExecutor")


class NomadLifecycle:
    """Own the entered :class:`NomadExecutor` and rebind it on config changes.

    The live entered executor (the one with an open aiohttp session) lives here
    in ``app.state.nomad_lifecycle`` rather than in the override snapshot, which
    stores only a diff-stable config fingerprint. :meth:`reconcile` is wired as
    the ``(TASKS_SETTINGS, NOMAD)`` rebind callback by ``tasks_lifespan``; it
    opens the new executor before swapping and closes the old one afterwards, so
    a reader resolving :attr:`current` after the swap sees the new open session.

    :param app: The FastAPI application whose ``state`` exposes the holder to
        request-scoped readers via ``get_executor``.
    :type app: FastAPI
    """

    def __init__(self, app: FastAPI) -> None:
        self._app = app
        self._current: NomadExecutor | None = None
        self._current_config: dict[str, Any] | None = None
        self._lock = asyncio.Lock()

    @property
    def current(self) -> NomadExecutor:
        """Return the live, entered executor.

        :return: The currently-entered :class:`NomadExecutor`.
        :rtype: NomadExecutor
        :raises RuntimeError: If accessed before :meth:`__aenter__` ran.
        """
        if self._current is None:
            raise RuntimeError("NomadLifecycle not started")
        return self._current

    def _desired(self) -> NomadExecutor:
        """Return the un-entered executor the current override config calls for.

        :return: A :class:`NomadExecutor` built from the effective ``NOMAD``
            override (the live YAML executor when no override is active).
        :rtype: NomadExecutor
        """
        return normalize_nomad_config_value(tasks_settings.NOMAD)

    async def __aenter__(self) -> Self:
        """Enter the executor the effective config calls for and publish self.

        :return: This holder, registered on ``app.state.nomad_lifecycle``.
        :rtype: Self
        """
        async with self._lock:
            desired = self._desired()
            self._current = await desired.__aenter__()
            self._current_config = desired.model_dump(
                mode="json", context=PRESERVE_CREDENTIALS_CONTEXT
            )
        self._app.state.nomad_lifecycle = self
        return self

    async def __aexit__(self, *_exc: object) -> None:
        """Exit the entered executor and unpublish the holder on shutdown."""
        async with self._lock:
            if self._current is not None:
                await self._current.__aexit__(None, None, None)
                self._current = None
        self._app.state.nomad_lifecycle = None

    async def reconcile(self) -> None:
        """Rebind the entered executor when the effective NOMAD config changed.

        Opens the new executor first, swaps the reference (a GIL-atomic
        assignment, so readers of :attr:`current` see either the old or the new
        executor but never a half-built one), then retires the old one. A no-op
        when the config is unchanged. A construction failure propagates to the
        refresher's per-cycle handler, leaving the old executor live.

        The new executor is entered *inside* the lock so the compare-and-swap is
        atomic against a concurrent reconcile. This is safe because
        :meth:`NomadExecutor.__aenter__` only builds an aiohttp ``ClientSession``
        (no network I/O), so it never blocks the lock for a meaningful duration;
        the old executor is retired *outside* the lock to keep shutdown's
        :meth:`__aexit__` from waiting on the close.

        The old executor is retired rather than closed outright: routes that
        resolved it stream off that instance for the whole response, so it stays
        open until the last of them releases it.

        :raises ValidationError: If the overridden config fingerprint cannot be
            reconstructed into a :class:`NomadExecutor` (propagated from
            :func:`normalize_nomad_config_value`).
        :raises TypeError: If the effective ``NOMAD`` value is neither a mapping
            nor a :class:`NomadExecutor` (also from
            :func:`normalize_nomad_config_value`).
        """
        desired = self._desired()
        desired_config = desired.model_dump(
            mode="json", context=PRESERVE_CREDENTIALS_CONTEXT
        )
        async with self._lock:
            if desired_config == self._current_config:
                return
            new = await desired.__aenter__()
            old, self._current = self._current, new
            self._current_config = desired_config
        if old is not None:
            await old.close_when_idle()

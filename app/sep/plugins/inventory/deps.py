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

"""Define dependencies for the Inventory plugin."""

from collections.abc import Callable
from typing import Annotated, NamedTuple

from fastapi import Depends

from app.core.config import settings
from app.core.exceptions import HTTPBadRequestException
from app.core.utils import import_var
from app.inventory.config import inventory_settings
from app.sep.config import sep_settings
from app.sep.deps import InventoryClient, TasksClient
from app.sep.sync.models import BaseSyncer
from app.tasks.config import tasks_settings


class AvailableSyncer(NamedTuple):
    """Provide template-facing metadata for an available syncer.

    :ivar name: The fully qualified ``"module.ClassName"`` identifier matching
        ``BaseSyncer.get_name()`` and the value persisted in
        ``SyncInstance.syncer``. Used as the wire identifier in form payloads.
    :vartype name: str
    :ivar display_name: The human-readable label rendered in the dropdown
        (the syncer class's short name with any trailing ``Syncer`` suffix
        stripped).
    :vartype display_name: str
    """

    name: str
    display_name: str


def _get_syncer_qualified_name(syncer: BaseSyncer) -> str:
    """Return the canonical fully qualified identifier for a syncer instance.

    Equivalent to ``BaseSyncer.get_name()`` but implemented as a free function
    so test stubs do not need to expose the ``get_name`` classmethod — any
    Python class exposes ``__module__`` and ``__name__``.

    :param syncer: The syncer instance to identify.
    :type syncer: BaseSyncer
    :return: The fully qualified ``"module.ClassName"`` identifier matching
        ``BaseSyncer.get_name()`` and the value stored in
        ``SyncInstance.syncer``.
    :rtype: str
    """
    cls = type(syncer)
    return f"{cls.__module__}.{cls.__name__}"


def build_available_syncers(
    syncers: list[BaseSyncer],
    can_sync_check: Callable[[BaseSyncer], bool],
) -> list[AvailableSyncer]:
    """Return metadata for the syncers that can handle the current entity.

    Disambiguate display labels when two or more matching syncers share the
    same short class name (e.g. ``app.sep.sync.syncers.legacy.MySQLSyncer``
    and ``app.sep.sync.syncers.new.MySQLSyncer``). In that case the colliding
    entries fall back to the fully qualified ``module.ClassName`` label so
    operators can tell the menu items apart; uncolliding entries keep their
    short, stripped display name.

    :param syncers: The configured ``BaseSyncer`` instances resolved by
        ``get_syncers``.
    :type syncers: list[BaseSyncer]
    :param can_sync_check: Callable invoked with each syncer instance that
        returns ``True`` when the syncer can sync the current entity.
    :type can_sync_check: Callable[[BaseSyncer], bool]
    :return: One ``AvailableSyncer`` per matching syncer, in declaration order.
    :rtype: list[AvailableSyncer]
    """
    matching = [syncer for syncer in syncers if can_sync_check(syncer)]
    short_display_names = []
    for syncer in matching:
        short = type(syncer).__name__
        short_display_names.append(short.removesuffix("Syncer") or short)
    display_counts = {}
    for short_display in short_display_names:
        display_counts[short_display] = display_counts.get(short_display, 0) + 1
    available = []
    for syncer, short_display in zip(matching, short_display_names, strict=True):
        qualified = _get_syncer_qualified_name(syncer)
        display_name = qualified if display_counts[short_display] > 1 else short_display
        available.append(
            AvailableSyncer(name=qualified, display_name=display_name),
        )
    return available


def filter_syncers_by_name(
    syncers: list[BaseSyncer],
    syncer_name: str | None,
    can_sync_check: Callable[[BaseSyncer], bool],
) -> list[BaseSyncer]:
    """Return the syncer selection for a sync route invocation.

    Distinguish two modes:

    - **Sync-all** (``syncer_name`` is ``None`` or empty) — return a shallow
      copy of ``syncers`` unchanged, in declaration order, with no capability
      pre-filter. Preserve the existing refresh-and-chain contract of
      ``run_*_sync``: the second and later syncers receive
      ``refresh_at_start=True`` and may become capable only after an earlier
      syncer mutates the entity. Pre-filtering would silently break that
      contract.
    - **Targeted** (``syncer_name`` present) — return the single syncer whose
      fully qualified name matches and whose capability check currently
      returns ``True``. Raise ``HTTPBadRequestException`` on an empty match
      set so crafted or stale POSTs do not become silent no-ops when
      ``run_*_sync(*[])`` is called.

    :param syncers: The syncers injected by ``SyncersDep``.
    :type syncers: list[BaseSyncer]
    :param syncer_name: The fully qualified syncer name submitted via the
        form (e.g. ``"app.sep.sync.syncers.pmm.PMMSyncer"``), or ``None`` /
        empty string to select the sync-all path.
    :type syncer_name: str | None
    :param can_sync_check: The entity-type capability check for the current
        request. Only consulted in the targeted path.
    :type can_sync_check: Callable[[BaseSyncer], bool]
    :return: The resolved list of syncers to hand to ``run_*_sync``.
    :rtype: list[BaseSyncer]
    :raises HTTPBadRequestException: In targeted mode, when no configured
        syncer both matches ``syncer_name`` and passes the capability check.
    """
    if not syncer_name:
        return list(syncers)
    matched = [
        syncer
        for syncer in syncers
        if _get_syncer_qualified_name(syncer) == syncer_name and can_sync_check(syncer)
    ]
    if not matched:
        raise HTTPBadRequestException(
            f"Unknown or inapplicable syncer: {syncer_name!r}",
        )
    return matched


def get_syncers(
    inventory_api: InventoryClient, tasks_api: TasksClient
) -> list[BaseSyncer]:
    """Initialize and return a list of BaseSyncer instances based on configuration.

    Import and initialize syncer classes as specified in the SEP settings, providing
    the necessary API clients and configuration parameters.

    :param inventory_api: The API client used to interact with the inventory service.
    :type inventory_api: InventoryClient
    :param tasks_api: The API client used to interact with the task service.
    :type tasks_api: TasksClient
    :return: A list of initialized ``BaseSyncer`` instances.
    :rtype: list[BaseSyncer]
    """
    syncers = []
    for sync_option in sep_settings.SYNCERS:
        syncer_class = import_var(sync_option.syncer)
        syncers.append(
            syncer_class(
                inventory_api=inventory_api,
                tasks_api=tasks_api,
                **sync_option.model_dump(exclude={"syncer"}),
            ),
        )
    return syncers


SyncersDep = Annotated[list[BaseSyncer], Depends(get_syncers)]


async def get_syncers_standalone() -> list[BaseSyncer]:
    """Initialize syncer instances with API clients constructed from settings.

    Construct ``RemoteAPI`` clients for the inventory and tasks services from
    application settings, then build syncers the same way the request-context
    dependency does. Used by scheduled tasks that run outside of request
    context.

    :return: A list of initialized ``BaseSyncer`` instances.
    :rtype: list[BaseSyncer]
    """
    inventory_api = await settings.get_remote_api(
        endpoint=sep_settings.INVENTORY_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=inventory_settings.SSL_KEYFILE,
        ssl_certfile=inventory_settings.SSL_CERTFILE,
        logger_name="inventory_api",
    )
    tasks_api = await settings.get_remote_api(
        endpoint=sep_settings.TASKS_ENDPOINT,
        ssl_cafile=settings.SSL_CAFILE,
        ssl_keyfile=tasks_settings.SSL_KEYFILE,
        ssl_certfile=tasks_settings.SSL_CERTFILE,
        logger_name="tasks_api",
    )
    syncers = []
    for sync_option in sep_settings.SYNCERS:
        syncer_class = import_var(sync_option.syncer)
        syncers.append(
            syncer_class(
                inventory_api=inventory_api,
                tasks_api=tasks_api,
                **sync_option.model_dump(exclude={"syncer"}),
            ),
        )
    return syncers

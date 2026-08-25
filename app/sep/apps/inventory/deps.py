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

import json
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict

from app.core.config import settings
from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPNotFoundException,
    HTTPUnprocessableEntityException,
)
from app.core.security import require_internal_token
from app.core.utils import import_var
from app.inventory.config import inventory_settings
from app.sep.apps.inventory.models import SyncRunSummary
from app.sep.config import sep_settings, SyncOptions
from app.sep.deps import InventoryClient, TasksClient
from app.sep.sync.models import BaseSyncer
from app.tasks.config import tasks_settings

INVENTORY_PLUGIN_ENTITY_NAMES = frozenset({"nodes", "services", "schemas", "tables"})

# Single source of truth for the read-only system-observation sub-resource
# segment, shared by the proxy route decorators and the forwarded-path helper
# so the inbound and forwarded paths cannot drift apart.
SYSTEM_OBSERVATION_SEGMENT = "system-observation"


class InventorySyncTriggerWrite(BaseModel):
    """Carry the optional JSON body for the ad-hoc inventory sync trigger.

    A ``None`` or empty ``syncer`` selects the sync-all path; a non-empty
    string targets a single configured syncer by its fully qualified
    ``"module.ClassName"`` identifier. Unknown fields are rejected with
    HTTP 422 so a typo on the client never silently degrades to sync-all.

    :param syncer: Fully qualified syncer name, or ``None`` for sync-all.
    :type syncer: str | None
    """

    model_config = ConfigDict(extra="forbid")

    syncer: str | None = None


class InventorySyncStatusResponse(BaseModel):
    """Represent the inventory sync status response.

    :param is_running: ``True`` when an inventory-wide sync is currently
        in progress; ``False`` otherwise.
    :type is_running: bool
    :param last_runs: The most recently recorded synchronization runs, newest first.
    :type last_runs: list[SyncRunSummary]
    """

    is_running: bool
    last_runs: list[SyncRunSummary] = []


class AvailableSyncer(BaseModel):
    """Provide template-facing metadata for an available syncer.

    :param name: The fully qualified ``"module.ClassName"`` identifier matching
        ``BaseSyncer.get_name()`` and the value persisted in
        ``SyncInstance.syncer``. Used as the wire identifier in form payloads.
    :type name: str
    :param display_name: The human-readable label rendered in the dropdown
        (the syncer class's short name with any trailing ``Syncer`` suffix
        stripped).
    :type display_name: str
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
      returns ``True``. Raise a domain-level ``ValueError`` on an empty match
      set so crafted or stale POSTs do not become silent no-ops when
      ``run_*_sync(*[])`` is called. Callers translate the error at the
      appropriate boundary: HTTP routes catch it and re-raise
      ``HTTPBadRequestException``, while the Celery caller lets it propagate
      as a task failure with a clean traceback.

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
    :raises ValueError: In targeted mode, when no configured syncer both
        matches ``syncer_name`` and passes the capability check.
    """
    if not syncer_name:
        return list(syncers)
    matched = [
        syncer
        for syncer in syncers
        if _get_syncer_qualified_name(syncer) == syncer_name and can_sync_check(syncer)
    ]
    if not matched:
        raise ValueError(
            f"Unknown or inapplicable syncer: {syncer_name!r}",
        )
    return matched


def _syncer_init_kwargs(sync_option: SyncOptions) -> dict[str, Any]:
    """Build constructor kwargs from a configured ``SyncOptions`` entry.

    Drops ``None`` leaves so optional nested models are not passed as explicit
    ``None``, which would override a syncer's default factory and fail
    validation.

    :param sync_option: One element from ``sep_settings.SYNCERS``.
    :type sync_option: SyncOptions
    :return: Keyword arguments for the syncer class constructor.
    :rtype: dict[str, Any]
    """
    return sync_option.model_dump(exclude={"syncer"}, exclude_none=True)


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
                **_syncer_init_kwargs(sync_option),
            ),
        )
    return syncers


SyncersDep = Annotated[list[BaseSyncer], Depends(get_syncers)]


def get_inventory_available_syncers(syncers: SyncersDep) -> list[AvailableSyncer]:
    """Return syncers capable of syncing inventory.

    :param syncers: Resolved syncer instances from ``SyncersDep``.
    :type syncers: list[BaseSyncer]
    :return: Filtered list of syncers that pass ``can_sync_inventory``.
    :rtype: list[AvailableSyncer]
    """
    return build_available_syncers(syncers, lambda s: s.can_sync_inventory())


InventoryAvailableSyncersDep = Annotated[
    list[AvailableSyncer], Depends(get_inventory_available_syncers)
]


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
                **_syncer_init_kwargs(sync_option),
            ),
        )
    return syncers


def require_inventory_plugin_entity(entity: str) -> str:
    """Normalize ``entity`` or raise HTTP 404 when it is not a known segment.

    :param entity: URL segment under ``/api/apps/inventory/``.
    :type entity: str
    :return: The same value when it is one of ``nodes``, ``services``,
        ``schemas``, or ``tables``.
    :rtype: str
    :raises HTTPNotFoundException: When ``entity`` is unknown.
    """
    if entity not in INVENTORY_PLUGIN_ENTITY_NAMES:
        raise HTTPNotFoundException("Unknown entity")
    return entity


def unwrap_inventory_plugin_list_payload(data: Any) -> list[Any]:
    """Return a list from an inventory list response (paginated or bare array).

    :param data: JSON payload from the inventory list endpoint.
    :type data: Any
    :return: ``data["items"]`` when that key holds a list; otherwise ``data``
        when it is already a list.
    :rtype: list[Any]
    :raises HTTPBadGatewayException: When the payload shape is unexpected.
    """
    if isinstance(data, dict) and "items" in data:
        items = data["items"]
        if isinstance(items, list):
            return items
    if isinstance(data, list):
        return data
    raise HTTPBadGatewayException("Unexpected inventory list response shape")


def inventory_service_list_path(entity: str) -> str:
    """Map a plugin entity name to the inventory service path for list GET.

    :param entity: One of ``nodes``, ``services``, ``schemas``, or ``tables``.
    :type entity: str
    :return: Path relative to the inventory API root (``/nodes/`` for nodes).
    :rtype: str
    """
    if entity == "nodes":
        return "/nodes/"
    return f"/{entity}/"


def inventory_service_detail_path(entity: str, item_id: int) -> str:
    """Map a plugin entity and id to the inventory path for detail GET/PUT/DELETE.

    :param entity: One of ``nodes``, ``services``, ``schemas``, or ``tables``.
    :type entity: str
    :param item_id: Primary key of the row.
    :type item_id: int
    :return: Path relative to the inventory API root.
    :rtype: str
    """
    if entity == "nodes":
        return f"/nodes/{item_id}"
    return f"/{entity}/{item_id}"


def inventory_system_observation_path(entity: str, item_id: int) -> str:
    """Map a plugin entity and id to the inventory system-observation sub-resource.

    Built by appending ``/system-observation`` to the detail path from
    ``inventory_service_detail_path`` so the sub-resource always tracks the
    canonical detail mapping and the two cannot drift. Targets the read-only
    system-observation endpoint exposed by the inventory sub-app. Only
    ``nodes`` and ``services`` carry an observation; callers reach this helper
    through the explicit per-entity proxy routes.

    :param entity: ``nodes`` or ``services``.
    :param item_id: Primary key of the node or service.
    :return: Path relative to the inventory API root.
    """
    return (
        f"{inventory_service_detail_path(entity, item_id)}/{SYSTEM_OBSERVATION_SEGMENT}"
    )


def _parse_positive_int_parent_id(value: Any, *, field_name: str) -> int:
    """Parse a parent id from JSON for nested inventory POST paths.

    Raw dict bodies skip FastAPI path/query validation; malformed values must
    surface as HTTP 422 instead of propagating ``ValueError`` as a 500.

    :param value: ``node_id``, ``service_id``, or ``schema_id`` from the body.
    :type value: Any
    :param field_name: Field label for error messages (e.g. ``node_id``).
    :type field_name: str
    :return: Strict positive integer id.
    :rtype: int
    :raises HTTPUnprocessableEntityException: When ``value`` is not a positive int.
    """
    if isinstance(value, bool):
        raise HTTPUnprocessableEntityException(f"{field_name} must be a valid integer")
    if isinstance(value, int):
        if value < 1:
            raise HTTPUnprocessableEntityException(
                f"{field_name} must be a positive integer",
            )
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped.isdigit():
            raise HTTPUnprocessableEntityException(
                f"{field_name} must be a valid integer"
            )
        parsed = int(stripped)
        if parsed < 1:
            raise HTTPUnprocessableEntityException(
                f"{field_name} must be a positive integer",
            )
        return parsed
    raise HTTPUnprocessableEntityException(f"{field_name} must be a valid integer")


def inventory_service_create_path(entity: str, body: dict[str, Any]) -> str:
    """Map a plugin entity and JSON body to the inventory path for POST.

    Nested creates require ``node_id``, ``service_id``, or ``schema_id`` in
    ``body`` and raise HTTP 422 when the parent id is missing.

    :param entity: One of ``nodes``, ``services``, ``schemas``, or ``tables``.
    :type entity: str
    :param body: Parsed create payload from the client.
    :type body: dict[str, Any]
    :return: Path relative to the inventory API root.
    :rtype: str
    :raises HTTPUnprocessableEntityException: When a required parent id is absent
        or not coercible to ``int``.
    :raises HTTPNotFoundException: When ``entity`` is unknown.
    """
    if entity == "nodes":
        return "/nodes/"
    if entity == "services":
        node_id = body.get("node_id")
        if node_id is None:
            raise HTTPUnprocessableEntityException(
                "node_id is required to create a service",
            )
        parsed_node_id = _parse_positive_int_parent_id(node_id, field_name="node_id")
        return f"/nodes/{parsed_node_id}/services/"
    if entity == "schemas":
        service_id = body.get("service_id")
        if service_id is None:
            raise HTTPUnprocessableEntityException(
                "service_id is required to create a schema",
            )
        parsed_service_id = _parse_positive_int_parent_id(
            service_id, field_name="service_id"
        )
        return f"/services/{parsed_service_id}/schemas/"
    if entity == "tables":
        schema_id = body.get("schema_id")
        if schema_id is None:
            raise HTTPUnprocessableEntityException(
                "schema_id is required to create a table",
            )
        parsed_schema_id = _parse_positive_int_parent_id(
            schema_id, field_name="schema_id"
        )
        return f"/schemas/{parsed_schema_id}/tables/"
    raise HTTPNotFoundException("Unknown entity")


def inventory_plugin_query_params(request: Request) -> dict[str, Any]:
    """Collect non-empty query string parameters from ``request``.

    :param request: The inbound HTTP request.
    :type request: Request
    :return: Key/value pairs with empty string values omitted.
    :rtype: dict[str, Any]
    """
    return {k: v for k, v in request.query_params.items() if v is not None and v != ""}


async def inventory_plugin_json_object_body(request: Request) -> dict[str, Any]:
    """Parse JSON from ``request`` and require a top-level object.

    Shared by inventory plugin POST/PUT handlers so body validation is not
    duplicated on each route.

    :param request: The inbound HTTP request.
    :type request: Request
    :return: Parsed JSON object body.
    :rtype: dict[str, Any]
    :raises HTTPUnprocessableEntityException: When the body is not valid JSON,
        cannot be decoded as UTF-8 for JSON parsing, or is not a JSON object.
    """
    try:
        body = await request.json()
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPUnprocessableEntityException(
            "JSON object body required",
        ) from None
    if not isinstance(body, dict):
        raise HTTPUnprocessableEntityException("JSON object body required")
    return body


InventoryPluginJsonObjectBody = Annotated[
    dict[str, Any],
    Depends(inventory_plugin_json_object_body),
]


InternalTokenDep = Annotated[str, Depends(require_internal_token)]

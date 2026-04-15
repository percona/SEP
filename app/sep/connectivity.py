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

"""Provide connectivity check helpers and an async LRU cache for task creation."""

import logging
from collections import OrderedDict
from collections.abc import Iterable
from typing import Any, cast

from aiohttp import ClientError
from async_lru import alru_cache
from fastapi import HTTPException
from starlette.requests import Request

from app.core.requests import RemoteAPI
from app.sep.middleware import messages

logger = logging.getLogger(__name__)

CACHE_TTL = 600
CHECK_TIMEOUT = 10
CACHE_MAXSIZE = 128

CONNECTIVITY_META_HOST_KEY = "_connectivity_host"
CONNECTIVITY_META_PORT_KEY = "_connectivity_port"
CONNECTIVITY_META_SERVICE_TYPE_KEY = "_connectivity_service_type"
CONNECTIVITY_TARGET_KEY = "_connectivity_target"
CONNECTIVITY_WARNING_KEY = "_connectivity_warning"

_LATEST_RESULTS: OrderedDict[tuple[str, str], bool] = OrderedDict()


def _record_latest_result(target: str, service_type: str, *, success: bool) -> None:
    """Record the most recent connectivity outcome for sync UI annotations.

    Maintain a bounded LRU snapshot of the latest connectivity outcome per
    ``(target, service_type)`` pair so the synchronous
    ``annotate_tasks_with_connectivity`` can flag tasks without consulting
    ``alru_cache`` (which exposes no public sync peek). The snapshot has no
    TTL of its own; ``alru_cache`` remains the authoritative TTL store and
    the snapshot is best-effort, refreshed each time
    ``check_and_warn_connectivity`` runs.

    :param target: The Nomad node name.
    :type target: str
    :param service_type: The lowercase service type (e.g. ``mysql``).
    :type service_type: str
    :param success: Whether the most recent check succeeded.
    :type success: bool
    """
    key = (target, service_type)
    _LATEST_RESULTS[key] = success
    _LATEST_RESULTS.move_to_end(key)
    while len(_LATEST_RESULTS) > CACHE_MAXSIZE:
        _LATEST_RESULTS.popitem(last=False)


@alru_cache(maxsize=CACHE_MAXSIZE, ttl=CACHE_TTL)
async def _fetch_connectivity_result(
    tasks_api: RemoteAPI,
    target: str,
    host: str,
    port: int,
    service_type: str,
) -> tuple[bool, str | None]:
    """Run the Tasks API connectivity check and return ``(success, error)``.

    Memoize results by ``(tasks_api, target, host, port, service_type)`` so
    repeated checks within ``CACHE_TTL`` seconds skip the API roundtrip.
    ``RemoteAPI`` is hashable, so it participates in the cache key directly
    without any contextvar indirection.

    :param tasks_api: Authenticated Tasks API client.
    :type tasks_api: RemoteAPI
    :param target: The Nomad node name.
    :type target: str
    :param host: The database host address.
    :type host: str
    :param port: The database port.
    :type port: int
    :param service_type: The lowercase service type (e.g. ``mysql``).
    :type service_type: str
    :return: A tuple of ``(success, error)`` where ``error`` is ``None`` on
        success or carries a human-readable message on failure.
    :rtype: tuple[bool, str | None]
    """
    try:
        result = cast(
            "dict[str, Any]",
            await tasks_api.post(
                "/connectivity-check/",
                json={
                    "target": target,
                    "host": host,
                    "port": port,
                    "service_type": service_type,
                    "timeout": CHECK_TIMEOUT,
                },
            ),
        )
        return result.get("success", False), result.get("error")
    except HTTPException as exc:
        logger.debug(
            "Tasks API connectivity check returned error response", exc_info=True
        )
        error = (
            exc.detail if isinstance(exc.detail, str) else "Connectivity check failed"
        )
        return False, error
    except (OSError, TimeoutError, ClientError):
        logger.debug("Could not reach Tasks API for connectivity check", exc_info=True)
        return False, "Could not reach the Tasks API"


async def check_and_warn_connectivity(
    request: Request,
    tasks_api: RemoteAPI,
    *,
    target: str,
    host: str,
    port: int,
    service_type: str,
) -> None:
    """Run a connectivity check and flash a warning on failure.

    Delegate the actual Tasks API call to ``_fetch_connectivity_result`` so
    its result is memoized via ``alru_cache``. Subsequent calls with the
    same ``(tasks_api, target, host, port, service_type)`` tuple short-
    circuit until ``CACHE_TTL`` seconds elapse.

    :param request: The HTTP request (for flash messages).
    :type request: Request
    :param tasks_api: Authenticated Tasks API client.
    :type tasks_api: RemoteAPI
    :param target: The Nomad node name.
    :type target: str
    :param host: The database host address.
    :type host: str
    :param port: The database port.
    :type port: int
    :param service_type: The lowercase service type (e.g. ``mysql``).
    :type service_type: str
    """
    success, error = await _fetch_connectivity_result(
        tasks_api, target, host, port, service_type
    )
    _record_latest_result(target, service_type, success=success)

    if not success:
        messages.warning(
            request,
            f"Connectivity warning for {target} ({service_type}): "
            f"{error or 'check failed'}",
        )


async def maybe_check_connectivity(
    request: Request,
    tasks_api: RemoteAPI,
    meta: dict[str, Any],
    *,
    check_connectivity: bool = True,
) -> None:
    """Run ``check_and_warn_connectivity`` when ``meta`` carries connectivity data.

    Extract ``target``, ``_connectivity_host``, ``_connectivity_port``, and
    ``_connectivity_service_type`` from ``meta`` and delegate to
    ``check_and_warn_connectivity``. Return silently when any of those keys
    are missing or falsy, which lets task-creation routes invoke this helper
    unconditionally without inspecting the task payload themselves.

    :param request: The HTTP request (for flash messages).
    :type request: Request
    :param tasks_api: Authenticated Tasks API client.
    :type tasks_api: RemoteAPI
    :param meta: The ``task.data["meta"]`` mapping from the created task.
    :type meta: dict[str, Any]
    :param check_connectivity: If ``False``, skip both the Tasks API call and
        the ``_LATEST_RESULTS`` cache write. Honors the per-task opt-out from
        the SEP task creation forms.
    :type check_connectivity: bool
    """
    if not check_connectivity:
        return
    target = meta.get("target")
    host = meta.get(CONNECTIVITY_META_HOST_KEY)
    port = meta.get(CONNECTIVITY_META_PORT_KEY)
    service_type = meta.get(CONNECTIVITY_META_SERVICE_TYPE_KEY)
    if target and host and port and service_type:
        await check_and_warn_connectivity(
            request,
            tasks_api,
            target=target,
            host=host,
            port=port,
            service_type=service_type,
        )


def annotate_tasks_with_connectivity(tasks: Iterable[dict[str, Any]]) -> None:
    """Add ``_connectivity_warning`` flag to tasks based on the latest results.

    Support two task dict formats:

    - Raw task dicts with ``data.meta`` containing ``target`` and
      ``_connectivity_service_type``.
    - Enriched ``task_info`` dicts with top-level ``_connectivity_target`` and
      ``_connectivity_service_type`` keys.

    :param tasks: The iterable of task dictionaries to annotate in-place.
    :type tasks: Iterable[dict[str, Any]]
    """
    for task in tasks:
        target = task.get(CONNECTIVITY_TARGET_KEY)
        service_type = task.get(CONNECTIVITY_META_SERVICE_TYPE_KEY)
        if target is None or service_type is None:
            meta = task.get("data", {}).get("meta", {})
            target = meta.get("target")
            service_type = meta.get(CONNECTIVITY_META_SERVICE_TYPE_KEY)
        if target and service_type:
            success = _LATEST_RESULTS.get((target, service_type))
            if success is not None:
                task[CONNECTIVITY_WARNING_KEY] = not success

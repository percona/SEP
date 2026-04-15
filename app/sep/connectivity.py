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

"""Provide connectivity check helpers and in-memory cache for task creation."""

import logging
import time

from aiohttp import ClientError
from fastapi import HTTPException
from starlette.requests import Request

from app.core.requests import RemoteAPI
from app.sep.middleware import messages

logger = logging.getLogger(__name__)

CACHE_TTL = 600
CHECK_TIMEOUT = 10

_connectivity_cache: dict[tuple[str, str], tuple[bool, str | None, float]] = {}


def get_connectivity_status(target: str, service_type: str) -> bool | None:
    """Return cached connectivity status or ``None`` if not cached or expired.

    :param target: The Nomad node name.
    :type target: str
    :param service_type: The database service type (e.g. ``MYSQL``).
    :type service_type: str
    :return: ``True`` if connectivity succeeded, ``False`` if it failed,
        or ``None`` if the cache entry is missing or expired.
    :rtype: bool | None
    """
    key = (target, service_type)
    entry = _connectivity_cache.get(key)
    if entry is None:
        return None
    success, _, timestamp = entry
    if time.monotonic() - timestamp > CACHE_TTL:
        del _connectivity_cache[key]
        return None
    return success


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

    Short-circuit on a cache hit: if ``get_connectivity_status`` returns a
    non-``None`` value for ``(target, service_type)``, skip the Tasks API
    call entirely. On a cached failure, the previously-stored error message
    is used to flash the warning; on a cached success, the helper returns
    silently.

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
    :param service_type: One of ``MYSQL``, ``POSTGRESQL``, ``MONGODB``.
    :type service_type: str
    """
    cached = get_connectivity_status(target, service_type)
    if cached is not None:
        if not cached:
            entry = _connectivity_cache.get((target, service_type))
            cached_error = entry[1] if entry else None
            messages.warning(
                request,
                f"Connectivity warning for {target} ({service_type}): "
                f"{cached_error or 'check failed'}",
            )
        return

    try:
        result = await tasks_api.post(
            "/connectivity-check/",
            json={
                "target": target,
                "host": host,
                "port": port,
                "service_type": service_type,
                "timeout": CHECK_TIMEOUT,
            },
        )
        success = result.get("success", False)
        error = result.get("error")
    except HTTPException as exc:
        logger.debug(
            "Tasks API connectivity check returned error response", exc_info=True
        )
        success = False
        error = (
            exc.detail if isinstance(exc.detail, str) else "Connectivity check failed"
        )
    except (OSError, TimeoutError, ClientError):
        logger.debug("Could not reach Tasks API for connectivity check", exc_info=True)
        success = False
        error = "Could not reach the Tasks API"

    _connectivity_cache[(target, service_type)] = (success, error, time.monotonic())

    if not success:
        messages.warning(
            request,
            f"Connectivity warning for {target} ({service_type}): "
            f"{error or 'check failed'}",
        )


async def maybe_check_connectivity(
    request: Request,
    tasks_api: RemoteAPI,
    meta: dict,
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
    :type meta: dict
    """
    target = meta.get("target")
    host = meta.get("_connectivity_host")
    port = meta.get("_connectivity_port")
    service_type = meta.get("_connectivity_service_type")
    if not target or not host or not port or not service_type:
        return

    await check_and_warn_connectivity(
        request,
        tasks_api,
        target=target,
        host=host,
        port=int(port),
        service_type=service_type,
    )


def annotate_tasks_with_connectivity(tasks: list[dict]) -> None:
    """Add ``_connectivity_warning`` flag to tasks based on cached check results.

    Support two task dict formats:

    - Raw task dicts with ``data.meta`` containing ``target`` and
      ``_connectivity_service_type``.
    - Enriched ``task_info`` dicts with top-level ``_connectivity_target`` and
      ``_connectivity_service_type`` keys.

    :param tasks: The list of task dictionaries to annotate in-place.
    :type tasks: list[dict]
    """
    for task in tasks:
        target = task.get("_connectivity_target")
        service_type = task.get("_connectivity_service_type")
        if target is None or service_type is None:
            meta = task.get("data", {}).get("meta", {})
            target = meta.get("target")
            service_type = meta.get("_connectivity_service_type")
        if target and service_type:
            status = get_connectivity_status(target, service_type)
            if status is not None:
                task["_connectivity_warning"] = not status

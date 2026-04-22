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

"""PMM annotation helpers for task lifecycle events."""

import asyncio
import copy
import logging
from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm.attributes import NO_VALUE

from app.core.config import settings
from app.core.requests.remote_api import RemoteAPI
from app.tasks.models import TaskExecutionRequest, TaskHistory

_EXECUTION_REQUEST_ATTR = "execution_request"

logger = logging.getLogger(__name__)

_background_tasks = set()


def execution_request_for_pmm_snapshot(queue_item: TaskHistory) -> TaskExecutionRequest:
    """Return the task execution request used to build a PMM annotation.

    The deferred ``TaskHistory.execution_request`` (SEP-816) can raise
    ``MissingGreenlet`` on async engines if read through the attribute after the load
    session has closed. When the column is already in memory, use the ORM
    :attr:`loaded_value` (see SEP-1021); otherwise read ``queue_item.execution_request``.

    :param queue_item: The task history record.
    :type queue_item: TaskHistory
    :return: The request whose ``task``, ``target``, and ``meta`` are snapshotted.
    :rtype: TaskExecutionRequest
    """
    state = sa_inspect(queue_item).attrs.execution_request
    if state.loaded_value is not NO_VALUE:
        return state.loaded_value
    return queue_item.execution_request


async def create_pmm_annotation(
    text: str,
    node_name: str,
    tags: list[str] | None = None,
    service_names: list[str] | None = None,
) -> None:
    """Create a PMM annotation via POST ``/v1/management/annotations``.

    Best-effort: errors are logged but never raised. Callers should
    schedule this via ``asyncio.create_task()`` for non-blocking behavior;
    awaiting directly blocks for up to ``settings.PMM.annotations_timeout`` seconds.

    :param text: Annotation text (e.g. ``"SEP backup_data - STARTED"``).
    :type text: str
    :param node_name: PMM node name from execution target.
    :type node_name: str
    :param tags: Optional tags for the annotation.
    :type tags: list[str] | None
    :param service_names: PMM service names from task metadata.
    :type service_names: list[str] | None
    """
    if not settings.PMM.annotations_enabled:
        return
    if not settings.PMM.endpoint or not settings.PMM.api_key:
        logger.debug("PMM annotation skipped: endpoint or api_key not configured")
        return

    try:
        api = await settings.get_remote_api(
            RemoteAPI,
            endpoint=settings.PMM.endpoint,
            verify_ssl=settings.PMM.verify_ssl,
            error_detail_key="message",
            error_code_key="code",
        )
        with api.auth(settings.PMM.api_key.get_secret_value()):
            await asyncio.wait_for(
                api.post(
                    "/v1/management/annotations",
                    json={
                        "text": text,
                        "tags": tags or [],
                        "node_name": node_name,
                        "service_names": service_names or [],
                    },
                ),
                timeout=settings.PMM.annotations_timeout,
            )
        logger.info("PMM annotation created: %s (node=%s)", text, node_name)
    except Exception:
        logger.exception("Failed to create PMM annotation: %s", text)


async def annotate_task_event(
    *,
    task_name: str,
    target: str,
    meta: dict[str, Any] | None,
    event: str,
) -> None:
    """Create a PMM annotation for a task lifecycle event.

    Read ``_service_names`` (list) or ``_service_name`` (str) from the
    task execution metadata. Accept primitives rather than an ORM
    instance so the coroutine is safe to run after the originating
    request session has closed (see SEP-1009).

    :param task_name: The task name (from ``TaskExecutionRequest.task``).
    :type task_name: str
    :param target: The execution target node (from ``TaskExecutionRequest.target``).
    :type target: str
    :param meta: The task execution metadata (from ``TaskExecutionRequest.meta``).
    :type meta: dict[str, Any] | None
    :param event: The event label (e.g. ``"STARTED"``, ``"COMPLETED"``, ``"FAILED"``).
    :type event: str
    """
    safe_meta = meta or {}
    service_names = safe_meta.get("_service_names")
    if service_names is None:
        single = safe_meta.get("_service_name")
        service_names = [single] if single else []

    await create_pmm_annotation(
        text=f"SEP {task_name} - {event}",
        node_name=target,
        tags=["sep", task_name, event.lower()],
        service_names=service_names,
    )


def schedule_annotation(
    queue_item: TaskHistory,
    event: str,
) -> None:
    """Schedule a fire-and-forget PMM annotation as a background task.

    Snapshot the request fields synchronously so the background
    coroutine never touches ORM attributes after the originating
    session has closed. See SEP-1009.

    Precondition: ``queue_item.execution_request`` must already be
    loaded. The column is declared ``deferred=True`` as a ``column_property``
    (``app/tasks/models.py``); touching it here from sync code triggers a
    lazy SELECT that raises :class:`sqlalchemy.exc.MissingGreenlet` on
    async drivers (asyncpg, aiosqlite) when the instance is still
    attached, and :class:`sqlalchemy.orm.exc.DetachedInstanceError` when
    the session has closed. Callers that hand over a freshly-saved
    instance — ``TaskHistoryManager.save`` re-defers the column via its
    internal ``session.refresh(instance)`` — must run
    ``await session.refresh(obj, attribute_names=["execution_request"])``
    first (see ``app/tasks/routes.py`` and
    ``app/tasks/connectivity/service.py`` for the canonical pattern).
    See SEP-1017.

    ``meta`` is deep-copied so the background task observes the values
    at scheduling time even if the originating request mutates nested
    structures inside the attribute afterwards.

    :param queue_item: The task history record.
    :type queue_item: TaskHistory
    :param event: The event label (e.g. ``"STARTED"``, ``"COMPLETED"``).
    :type event: str
    :raises RuntimeError: If ``execution_request`` is not loaded on
        ``queue_item``.
    """
    execution_request = execution_request_for_pmm_snapshot(queue_item)
    if _EXECUTION_REQUEST_ATTR in sa_inspect(queue_item).unloaded:
        raise RuntimeError(
            "schedule_annotation requires queue_item.execution_request "
            "to be loaded. Call "
            '`await session.refresh(obj, attribute_names=["execution_request"])`'
            " before schedule_annotation(obj, ...). The column is "
            "deferred=True and a sync access triggers MissingGreenlet on "
            "asyncpg/aiosqlite (or DetachedInstanceError once the session "
            "has closed)."
        )
    execution_request = queue_item.execution_request
    meta = copy.deepcopy(execution_request.meta)
    task = asyncio.create_task(
        annotate_task_event(
            task_name=execution_request.task,
            target=execution_request.target,
            meta=meta,
            event=event,
        )
    )
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

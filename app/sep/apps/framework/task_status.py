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

"""Provide shared helpers for deriving task status from history payloads."""

import logging
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any

from app.sep.deps import TaskAPI
from app.tasks.models import (
    LATEST_HISTORY_STATUS_NAMES_MAX,
    TaskHistoryLatestStatus,
    TaskHistoryStatusEnum,
)

logger = logging.getLogger(__name__)


def _extract_last_finished_at(
    histories: Iterable[dict[str, Any]],
) -> datetime | None:
    """Return the ``max`` ``finished_at`` across status-bearing history rows.

    Mirrors the tasks-side ``max(finished_at)`` window aggregation (which filters
    ``status IS NOT NULL``) so the single-task detail surface agrees with the
    batch list surface: an in-progress re-run (whose newest row has no
    ``finished_at``) still reports the prior completion time.

    :param histories: Task history dicts (order-independent for this aggregate).
    :return: The most recent completion timestamp, or ``None`` when no run has
        ever finished.
    """
    finishes = [
        datetime.fromisoformat(value)
        for history in histories
        if history.get("status") is not None
        and (value := history.get("finished_at")) is not None
    ]
    return max(finishes, default=None)


def extract_latest_task_status(
    histories: Iterable[dict[str, Any]],
) -> TaskHistoryStatusEnum | None:
    """Return the latest known status from a task history payload.

    Histories are expected ordered newest-first (matching the Tasks API
    ``/{task}/history/`` contract). The first entry with a non-``None``
    ``status`` wins; an empty iterable or all-``None`` payloads yield ``None``.

    :param histories: Task history dicts, newest-first.
    :type histories: Iterable[dict[str, Any]]
    :return: The latest known status, or ``None`` if none is present.
    :rtype: TaskHistoryStatusEnum | None
    :raises ValueError: If a non-``None`` status is outside ``TaskHistoryStatusEnum``.
    """
    for history in histories:
        if (status := history.get("status")) is not None:
            return TaskHistoryStatusEnum(status)
    return None


async def get_task_latest_status(
    tasks_api: TaskAPI,
    task_name: str,
    *,
    params: dict[str, Any] | None = None,
) -> TaskHistoryStatusEnum | None:
    """Fetch ``GET /{task_name}/history/`` and return its latest status.

    :param tasks_api: The TaskAPI instance used to query task history.
    :type tasks_api: TaskAPI
    :param task_name: The name of the task whose history is queried.
    :type task_name: str
    :param params: Optional query parameters forwarded verbatim to the GET.
    :type params: dict[str, Any] | None
    :return: The latest known task status, or ``None`` if no history exists.
    :rtype: TaskHistoryStatusEnum | None
    :raises ValueError: If the latest status is outside ``TaskHistoryStatusEnum``.
    :raises HTTPException: Propagated from ``tasks_api.get()`` on an upstream
        error response; callers that must tolerate it guard the call site.
    """
    response = await tasks_api.get(f"/{task_name}/history/", params=params)
    return extract_latest_task_status(response["items"])


def extract_latest_history(
    histories: Iterable[dict[str, Any]],
) -> TaskHistoryLatestStatus:
    """Return the latest-history projection from a task history payload.

    Combines :func:`extract_latest_task_status` (newest non-null status) with
    :func:`_extract_last_finished_at` (``max`` ``finished_at``) so list and
    detail surfaces derive the same projection. An empty or all-``None`` payload
    yields a projection with both fields ``None``.

    :param histories: Task history dicts, newest-first.
    :return: The latest-history projection (newest status + max finish time).
    :raises ValueError: If a non-``None`` status is outside ``TaskHistoryStatusEnum``.
    """
    histories = list(histories)
    return TaskHistoryLatestStatus(
        status=extract_latest_task_status(histories),
        finished_at=_extract_last_finished_at(histories),
    )


async def get_task_latest_history(
    tasks_api: TaskAPI,
    task_name: str,
    *,
    params: dict[str, Any] | None = None,
) -> TaskHistoryLatestStatus:
    """Fetch ``GET /{task_name}/history/`` and return its latest projection.

    :param tasks_api: The TaskAPI instance used to query task history.
    :param task_name: The name of the task whose history is queried.
    :param params: Optional query parameters forwarded verbatim to the GET.
    :return: The latest-history projection; both fields ``None`` when the task
        has no history.
    :raises ValueError: If the latest status is outside ``TaskHistoryStatusEnum``.
    :raises HTTPException: Propagated from ``tasks_api.get()`` on an upstream
        error response; callers that must tolerate it guard the call site.
    """
    response = await tasks_api.get(f"/{task_name}/history/", params=params)
    return extract_latest_history(response["items"])


def _parse_latest_history(value: Any) -> TaskHistoryLatestStatus | None:
    """Coerce a ``/history/latest`` wire value into a projection.

    Tolerates both a bare status string and the projection shape (a
    ``{status, finished_at}`` object) so older ``/history/latest`` payloads
    still parse during a rolling upgrade. ``None`` passes through unchanged.

    :param value: A single per-task value from a batch history response.
    :return: The parsed projection, or ``None`` when ``value`` is ``None``.
    :raises ValueError: If ``value`` carries a status outside
        ``TaskHistoryStatusEnum`` (``ValidationError`` subclasses ``ValueError``).
    """
    if value is None:
        return None
    if isinstance(value, str):
        return TaskHistoryLatestStatus(status=TaskHistoryStatusEnum(value))
    return TaskHistoryLatestStatus.model_validate(value)


async def batch_get_latest_statuses(
    tasks_api: TaskAPI,
    names: Sequence[str],
) -> dict[str, TaskHistoryLatestStatus | None]:
    """Resolve latest history projections for ``names`` via the batch endpoint.

    Empty ``names`` returns ``{}`` without an upstream call. Chunks at
    ``LATEST_HISTORY_STATUS_NAMES_MAX`` names per request; any failed chunk
    degrades to ``None`` for its names, preserving the full key set so consumers
    may index every requested name.

    :param tasks_api: The TaskAPI instance used to query task history.
    :param names: Task names to resolve latest history projections for.
    :return: A mapping from each requested name to its latest projection or
        ``None`` (no history / failed chunk).
    :raises ValueError: If the batch response carries a status outside
        ``TaskHistoryStatusEnum`` (the coercion runs outside the per-chunk
        failure guard).
    """
    if not names:
        return {}
    resolved = {}
    for start in range(0, len(names), LATEST_HISTORY_STATUS_NAMES_MAX):
        chunk = names[start : start + LATEST_HISTORY_STATUS_NAMES_MAX]
        try:
            response = await tasks_api.post(
                "/history/latest", json={"names": list(chunk)}
            )
        except Exception:
            logger.exception("Failed to batch-fetch latest history status")
            response = {}
        for name in chunk:
            resolved[name] = _parse_latest_history(response.get(name))
    return resolved

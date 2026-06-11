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
from typing import Any

from app.sep.deps import TaskAPI
from app.tasks.models import LATEST_HISTORY_STATUS_NAMES_MAX, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)


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
    """
    response = await tasks_api.get(f"/{task_name}/history/", params=params)
    return extract_latest_task_status(response["items"])


async def batch_get_latest_statuses(
    tasks_api: TaskAPI,
    names: Sequence[str],
) -> dict[str, TaskHistoryStatusEnum | None]:
    """Resolve latest history status for ``names`` via the batch endpoint.

    Empty ``names`` returns ``{}`` without an upstream call. Chunks at
    ``LATEST_HISTORY_STATUS_NAMES_MAX`` names per request; any failed chunk
    degrades to ``None`` for its names, preserving the full key set so consumers
    may index every requested name.

    :param tasks_api: The TaskAPI instance used to query task history.
    :type tasks_api: TaskAPI
    :param names: Task names to resolve latest non-null history statuses for.
    :type names: Sequence[str]
    :return: A mapping from each requested name to its latest status or ``None``.
    :rtype: dict[str, TaskHistoryStatusEnum | None]
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
            value = response.get(name)
            resolved[name] = TaskHistoryStatusEnum(value) if value is not None else None
    return resolved

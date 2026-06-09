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

from collections.abc import Iterable
from typing import Any

from app.tasks.models import TaskHistoryStatusEnum


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
    """
    for history in histories:
        if (status := history.get("status")) is not None:
            return TaskHistoryStatusEnum(status)
    return None

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

"""Shared task-shape guards for legacy ``data['_form']`` backfill reconstructors."""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

from app.sep.apps.framework.spec import RUN_PYTHON_TASK

if TYPE_CHECKING:
    from app.tasks.models import Task

__all__ = ["require_run_python_meta"]


def require_run_python_meta(task: Task) -> dict[str, Any] | None:
    """Return a config-bearing ``run-python`` task's ``meta`` dict, or ``None``.

    Validates the precondition four legacy reconstructors share: the task must be
    a ``run-python`` row whose ``meta`` is a dict carrying a ``config`` key.

    :param task: The persisted legacy task row.
    :return: The validated ``meta`` mapping, or ``None`` when the task is not a
        config-bearing ``run-python`` task.
    """
    data = task.data
    meta = data.get("meta")
    if (
        data.get("task") != RUN_PYTHON_TASK
        or not isinstance(meta, dict)
        or "config" not in meta
    ):
        return None
    return meta

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

"""Provide shared dependency factories for schema-driven plugins."""

from collections.abc import Awaitable, Callable

from app.sep.deps import get_task_by_name, TaskAPI
from app.tasks.models import Task


def make_task_dep(owner: str) -> Callable[[str, TaskAPI], Awaitable[Task]]:
    """Build a per-owner task-by-name dependency callable.

    Return a freshly-constructed coroutine function delegating to
    ``get_task_by_name(tasks_api, task_name, owner)``. Each plugin binds the
    result to a module-level name and wraps it in an ``Annotated`` alias, so the
    callable identity is stable per ``(plugin, owner)`` and FastAPI's
    per-request dependency cache scopes exactly as a module-level wrapper would.

    :param owner: The task owner the built dependency filters by.
    :return: A coroutine function resolving a ``Task`` by name for ``owner``.
    """

    async def get_task(task_name: str, tasks_api: TaskAPI) -> Task:
        return await get_task_by_name(tasks_api, task_name, owner)

    return get_task


def make_parent_resolver(
    get_task: Callable[[str, TaskAPI], Awaitable[Task]],
) -> Callable[[str, TaskAPI], Awaitable[Task]]:
    """Build a satellite-task-to-parent resolver around a per-owner getter.

    Return a coroutine that fetches ``task_name`` via ``get_task``, follows
    ``data["parent"]`` once when present (coercing the parent name with
    ``str(...)``), re-fetches the parent through the same getter, and otherwise
    returns the original task. Pair with :func:`make_task_dep` so plugins bind
    ``resolve_<app>_parent_task = make_parent_resolver(get_<owner>_task)``.

    :param get_task: A per-owner task-by-name callable (typically from
        :func:`make_task_dep`).
    :return: A coroutine resolving a task name to its parent when linked.
    """

    async def resolve_parent_task(task_name: str, tasks_api: TaskAPI) -> Task:
        task = await get_task(task_name, tasks_api)
        parent = task.data.get("parent")
        if parent:
            return await get_task(str(parent), tasks_api)
        return task

    return resolve_parent_task

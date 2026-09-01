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

from app.core.db.list_query import ListQuerySpec, make_query_param_dep
from app.sep.apps.framework.list_query import (
    InMemoryListQuery,
    InMemoryListQueryApplier,
)
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
    get_task_fn: Callable[[str, TaskAPI], Awaitable[Task]],
) -> Callable[[str, TaskAPI], Awaitable[Task]]:
    """Build a satellite-task-to-parent resolver around a per-owner getter.

    Return a coroutine that fetches ``task_name`` via ``get_task_fn``, follows
    ``data["parent"]`` once when present (coercing the parent name with
    ``str(...)``), re-fetches the parent through the same getter, and otherwise
    returns the original task. Pair with :func:`make_task_dep` so plugins bind
    ``resolve_<app>_parent_task = make_parent_resolver(get_<owner>_task)``.

    :param get_task_fn: A per-owner task-by-name callable (typically from
        :func:`make_task_dep`).
    :return: A coroutine resolving a task name to its parent when linked.
    """

    async def resolve_parent_task(task_name: str, tasks_api: TaskAPI) -> Task:
        task = await get_task_fn(task_name, tasks_api)
        parent = task.data.get("parent")
        if parent:
            return await get_task_fn(str(parent), tasks_api)
        return task

    return resolve_parent_task


def make_in_memory_list_query_dep(
    applier: InMemoryListQueryApplier,
) -> Callable[..., InMemoryListQuery]:
    """Build the request-boundary dependency for an in-memory list-query applier.

    The boundary itself is Core's, through
    :func:`~app.core.db.list_query.make_query_param_dep`, so the in-memory path and the
    SQL one expose the same parameters, publish the same allowlist ``enum`` and
    descriptions, and reject an out-of-allowlist sort key with the same HTTP 422 — Core
    maps the applier's :class:`~app.core.db.list_query.UnknownSortKeyError`. Only the
    resolved value object differs.

    Call this at wiring time and hand the result to ``Depends``; a fresh dependency is
    built per call rather than cached, because FastAPI binds each reflected parameter's
    ``Query`` declaration to the route it found it on.

    :param applier: The spec-bound applier whose allowlist bounds the request.
    :return: A dependency callable resolving the request into an
        :class:`~app.sep.apps.framework.list_query.InMemoryListQuery`.
    """

    # Core re-passes the spec it was given; the applier already binds it.
    def build(_spec: ListQuerySpec, sort: str, search: str | None) -> InMemoryListQuery:
        return applier.build_query(sort, search)

    return make_query_param_dep(applier.spec, build)

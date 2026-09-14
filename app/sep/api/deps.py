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

"""Define dependencies for the SEP-level ``/api/sep/`` JSON routes.

They live here rather than in ``app/sep/deps.py`` because the scheduling guard
resolves the owning app through ``get_app_registry()``, and the registry module
imports ``app.sep.deps``.
"""

from typing import Annotated

from fastapi import Body, Depends

from app.core.exceptions import (
    HTTPBadGatewayException,
    HTTPBadRequestException,
    HTTPUnprocessableEntityException,
)
from app.core.requests import as_json_object
from app.core.utils.fields import ArbitraryMapping
from app.sep.api.proxy import reraise_upstream_tasks_errors
from app.sep.apps.framework.registry import get_app_registry
from app.sep.deps import get_task_by_name, TaskAPI

_PATH_UNSAFE_CHARACTERS = frozenset("/?#%:")
"""Characters that let a task name restructure the upstream request URL."""

_PATH_UNSAFE_NAMES = frozenset({".", ".."})
"""Dot-segments that resolve to a different upstream path rather than a task."""


def _require_one_path_segment(task_name: str) -> None:
    """Refuse a task name that is more than one URL path segment.

    The guard reads the task through ``GET /{task_name}``, and
    :meth:`~app.core.requests.remote_api.BaseRemoteAPI.prepare_path` resolves that
    with ``urljoin``, which interprets ``/``, ``?``, ``#``, ``:`` and dot-segments
    rather than encoding them: a leading ``/`` makes the composed path ``//host/…``,
    which yarl reads as an absolute URL, so the request leaves the Tasks API for
    another host carrying the caller's bearer token. Against an endpoint whose
    ``base_path`` is not ``/``, ``prepare_path`` strips the leading slash first, so
    a ``:`` is read as a URI scheme and reaches ``urljoin`` as a scheme-relative
    reference. None of these are escapable at that layer, and a task named with one
    is unreachable through that endpoint anyway, so the name is refused here.

    :param task_name: The task name resolved from the request.
    :raises HTTPUnprocessableEntityException: If the name is a dot-segment or
        carries a character that would restructure the upstream path.
    """
    if task_name in _PATH_UNSAFE_NAMES or _PATH_UNSAFE_CHARACTERS.intersection(
        task_name
    ):
        raise HTTPUnprocessableEntityException(
            "The schedule's task must be a plain task name."
        )


async def ensure_task_schedulable(tasks_api: TaskAPI, task_name: str) -> None:
    """Refuse to schedule ``task_name`` unless an installed app offers scheduling.

    :param tasks_api: The Tasks API client used to read the task.
    :param task_name: The name of the task a schedule would run.
    :raises HTTPUnprocessableEntityException: If ``task_name`` is not a single
        plain URL path segment.
    :raises HTTPBadRequestException: If no installed app offers scheduling for the
        task — because no registered app claims its owner, or because one does and
        withholds the capability.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500), including the ``404`` for an unknown task.
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    _require_one_path_segment(task_name)
    with reraise_upstream_tasks_errors():
        task = await get_task_by_name(tasks_api, task_name)
    if not get_app_registry().owner_offers_scheduling(task.owner):
        raise HTTPBadRequestException(
            f"Task {task_name!r} cannot be scheduled: "
            "no installed app offers scheduling for it."
        )


async def require_schedulable_update(
    periodic_task_id: int,
    tasks_api: TaskAPI,
    body: Annotated[ArbitraryMapping, Body()],
) -> None:
    """Guard a schedule update on the task the schedule will run.

    The Tasks service stores the body's ``task`` and keeps the existing schedule's
    task when that is empty, so the guard resolves the same name. A present
    ``task`` that is not a string is refused here: the Tasks service writes a
    non-string one into the schedule's ``kwargs.task_name``, and an explicit
    ``null`` is not the omission the fallback below reads it as.

    :param periodic_task_id: The id of the schedule being replaced.
    :param tasks_api: The Tasks API client used to read the schedule and its task.
    :param body: The ``PeriodicTaskUpdate`` JSON body, read and left unaltered.
    :raises HTTPUnprocessableEntityException: If the body's ``task`` is present and
        not a string, or if the resolved name is not a single plain path segment.
    :raises HTTPBadRequestException: If no installed app offers scheduling for the
        resolved task.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500), including the ``404`` for an unknown schedule or task.
    :raises HTTPBadGatewayException: If the existing schedule carries no task name
        or is not a JSON object, and for an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    if "task" in body and not isinstance(body["task"], str):
        raise HTTPUnprocessableEntityException(
            "The schedule's task must be a task name string."
        )
    task_name = body.get("task")
    if not task_name:
        with reraise_upstream_tasks_errors():
            schedule = as_json_object(
                await tasks_api.get(f"/periodic/{periodic_task_id}")
            )
        task_name = schedule.get("task")
        if not isinstance(task_name, str) or not task_name:
            raise HTTPBadGatewayException(
                "The Tasks API returned a schedule with no task name."
            )
    await ensure_task_schedulable(tasks_api, task_name)


RequireSchedulableTask = Depends(ensure_task_schedulable)
RequireSchedulableUpdate = Depends(require_schedulable_update)

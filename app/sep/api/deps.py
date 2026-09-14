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


async def ensure_task_schedulable(tasks_api: TaskAPI, task_name: str) -> None:
    """Refuse to schedule ``task_name`` unless its owning app offers scheduling.

    :param tasks_api: The Tasks API client used to read the task.
    :param task_name: The name of the task a schedule would run.
    :raises HTTPBadRequestException: If no registered app owning the task offers
        scheduling.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500), including the ``404`` for an unknown task.
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    with reraise_upstream_tasks_errors():
        task = await get_task_by_name(tasks_api, task_name)
    if not get_app_registry().owner_offers_scheduling(task.owner):
        raise HTTPBadRequestException(
            f"Task {task_name!r} cannot be scheduled: its app does not offer scheduling."
        )


async def require_schedulable_task(task_name: str, tasks_api: TaskAPI) -> None:
    """Guard a schedule create on the scheduling capability of its task.

    :param task_name: The path's task name, which the new schedule runs.
    :param tasks_api: The Tasks API client used to read the task.
    :raises HTTPBadRequestException: If no registered app owning the task offers
        scheduling.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500), including the ``404`` for an unknown task.
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    await ensure_task_schedulable(tasks_api, task_name)


async def require_schedulable_update(
    periodic_task_id: int,
    tasks_api: TaskAPI,
    body: Annotated[ArbitraryMapping, Body()],
) -> None:
    """Guard a schedule update on the task the schedule will run.

    The Tasks service stores the body's ``task`` and keeps the existing schedule's
    task when that is empty, so the guard resolves the same name. A present
    ``task`` that is not a string is refused here, because the Tasks service
    accepts one and writes it into the schedule's ``kwargs.task_name``.

    :param periodic_task_id: The id of the schedule being replaced.
    :param tasks_api: The Tasks API client used to read the schedule and its task.
    :param body: The ``PeriodicTaskUpdate`` JSON body, read and left unaltered.
    :raises HTTPUnprocessableEntityException: If the body's ``task`` is present and
        not a string.
    :raises HTTPBadRequestException: If no registered app owning the resolved task
        offers scheduling.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500), including the ``404`` for an unknown schedule or task.
    :raises HTTPBadGatewayException: If the existing schedule carries no task name,
        and for an upstream server error (status >= 500) or a connection-level
        ``OSError``.
    """
    requested = body.get("task")
    if requested is not None and not isinstance(requested, str):
        raise HTTPUnprocessableEntityException(
            "The schedule's task must be a task name string."
        )
    task_name = requested
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


RequireSchedulableTask = Depends(require_schedulable_task)
RequireSchedulableUpdate = Depends(require_schedulable_update)

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

"""Define the ``/api/sep/periodic-tasks/`` JSON proxy routes.

Forward periodic-task CRUD to the Tasks sub-app through the SEP gateway so the
React frontend (``ScheduledTasksPanel``) reaches periodic-task list / create /
update / delete via SEP rather than calling ``/api/tasks`` directly. Each route
is a passthrough: it issues a single upstream call and forwards the response,
mapping upstream failures onto the SEP gateway error contract via
:func:`~app.sep.api.proxy.reraise_upstream_tasks_error`.
"""

from typing import Annotated, Any

from fastapi import APIRouter, Body, status

from app.sep.api.openapi import UPSTREAM_TASKS_502_RESPONSE
from app.sep.api.proxy import reraise_upstream_tasks_errors
from app.sep.deps import TaskAPI

router = APIRouter()


@router.get("/", responses=UPSTREAM_TASKS_502_RESPONSE)
async def list_periodic_tasks(tasks_api: TaskAPI) -> list[dict[str, Any]]:
    """Return the upstream periodic-task list through the SEP gateway.

    :param tasks_api: The Tasks API client used to fetch the upstream list.
    :return: The upstream periodic-task list, or ``[]`` when the upstream
        payload is not a list.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500).
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    with reraise_upstream_tasks_errors():
        result = await tasks_api.get("/periodic/")
    return result if isinstance(result, list) else []


@router.post(
    "/{task_name}/",
    status_code=status.HTTP_201_CREATED,
    responses=UPSTREAM_TASKS_502_RESPONSE,
)
async def create_periodic_task(
    task_name: str,
    tasks_api: TaskAPI,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Dispatch creation of a periodic task for ``task_name`` to the Tasks API.

    :param task_name: The task name the new periodic schedule runs.
    :param tasks_api: The Tasks API client used to create the periodic task.
    :param body: The ``PeriodicTaskCreate`` JSON body, forwarded verbatim.
    :return: The created periodic task as returned by the Tasks API.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500).
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    with reraise_upstream_tasks_errors():
        return await tasks_api.post(f"/{task_name}/periodic/", json=body)


@router.put("/{periodic_task_id}", responses=UPSTREAM_TASKS_502_RESPONSE)
async def update_periodic_task(
    periodic_task_id: int,
    tasks_api: TaskAPI,
    body: Annotated[dict[str, Any], Body()],
) -> dict[str, Any]:
    """Dispatch a full-replacement update of a periodic task to the Tasks API.

    :param periodic_task_id: The id of the periodic task to update.
    :param tasks_api: The Tasks API client used to update the periodic task.
    :param body: The ``PeriodicTaskUpdate`` JSON body, forwarded verbatim.
    :return: The updated periodic task as returned by the Tasks API.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500).
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    with reraise_upstream_tasks_errors():
        return await tasks_api.put(f"/periodic/{periodic_task_id}", json=body)


@router.delete(
    "/{periodic_task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=UPSTREAM_TASKS_502_RESPONSE,
)
async def delete_periodic_task(periodic_task_id: int, tasks_api: TaskAPI) -> None:
    """Dispatch deletion of a periodic task to the Tasks API.

    :param periodic_task_id: The id of the periodic task to delete.
    :param tasks_api: The Tasks API client used to delete the periodic task.
    :raises HTTPException: Re-raised unchanged for an upstream client error
        (status < 500).
    :raises HTTPBadGatewayException: For an upstream server error (status >= 500)
        or a connection-level ``OSError``.
    """
    with reraise_upstream_tasks_errors():
        await tasks_api.delete(f"/periodic/{periodic_task_id}")

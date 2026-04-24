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

"""Define routes for the Tasks API."""

import json
import logging

from fastapi import APIRouter, status
from sqlalchemy_celery_beat import PeriodicTask

from app.api.deps import IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.tasks.crud import TaskManager
from app.tasks.deps import (
    get_executable_task_by_name,
    SessionDep,
    validate_chain_task_names,
)
from app.tasks.models import (
    TaskOwner,
)
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.deps import PeriodicTaskDep
from app.tasks.periodic.models import (
    PeriodicTaskResponse,
    PeriodicTaskUpdate,
)

router = APIRouter(prefix="/periodic", tags=["periodic", "schedule", "tasks"])

logger = logging.getLogger(__name__)


# TODO: Pagination  # noqa: TD002, TD003
@router.get(
    "/",
    dependencies=[IsAuthenticatedDep],
    response_model=list[PeriodicTaskResponse],
)
async def list_periodic_tasks(
    session: CeleryBeatSessionDep,
    tasks_session: SessionDep,
    owner: TaskOwner | None = None,
    enabled: bool | None = None,
) -> list[PeriodicTask]:
    """List all periodic tasks."""
    if owner is None:
        return await PeriodicTaskManager.list(session=session, enabled=enabled)
    tasks_names = [
        task.name
        for task in await TaskManager.list_active(session=tasks_session, owner=owner)
    ]
    return await PeriodicTaskManager.list_by_task_names(
        session, *tasks_names, enabled=enabled
    )


@router.get("/{periodic_task_id}", dependencies=[IsAuthenticatedDep])
async def retrieve_periodic_task(
    periodic_task: PeriodicTaskDep,
) -> PeriodicTaskResponse:
    """Retrieve a periodic task by ID."""
    return periodic_task


@router.put(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
    response_model=PeriodicTaskResponse,
)
async def update_periodic_task(
    session: CeleryBeatSessionDep,
    tasks_session: SessionDep,
    existing_task: PeriodicTaskDep,
    updated_task: PeriodicTaskUpdate,
) -> PeriodicTask:
    """Update a periodic task."""
    updated_kwargs = json.loads(updated_task.kwargs)
    existing_kwargs = json.loads(existing_task.kwargs)
    task_name = updated_kwargs.get("task_name") or existing_kwargs["task_name"]
    if task_name != existing_kwargs["task_name"]:
        await get_executable_task_by_name(tasks_session, task_name)

    updated_chain = (
        updated_task.execute_request.chain_task_names
        if updated_task.execute_request
        and updated_task.execute_request.chain_task_names
        else None
    )
    existing_execution_data = existing_kwargs.get("execution_data") or {}
    existing_chain = existing_execution_data.get("chain_task_names")

    if updated_chain:
        seen = set()
        unique_chain = []
        for item in updated_chain:
            if item not in seen:
                unique_chain.append(item)
                seen.add(item)

        if updated_task.execute_request:
            updated_task.execute_request.chain_task_names = unique_chain
        updated_chain = unique_chain

    if updated_task.execute_request is None and existing_execution_data:
        from app.tasks.periodic.models import PeriodicTaskExecuteRequest

        updated_task.execute_request = PeriodicTaskExecuteRequest(
            **existing_execution_data
        )
        logger.debug(
            "UPDATE PERIODIC TASK - Reconstructed execute_request from existing data"
        )

    # Validate only if chain is being added or modified (not when it's unchanged)
    if updated_chain and updated_chain != existing_chain:
        logger.debug("UPDATE PERIODIC TASK - VALIDATING CHAIN (changed)")
        await validate_chain_task_names(
            tasks_session,
            updated_chain,
            await get_executable_task_by_name(tasks_session, task_name),
        )
    else:
        logger.debug("UPDATE PERIODIC TASK - SKIPPING CHAIN VALIDATION (unchanged)")

    logger.debug("Updating periodic task %s", existing_task.id)
    return await PeriodicTaskManager.update(session, existing_task, updated_task)


@router.delete(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_periodic_task(
    session: CeleryBeatSessionDep, periodic_task: PeriodicTaskDep
) -> None:
    """Delete a periodic task."""
    logger.debug("Deleting periodic task %s", periodic_task)
    await PeriodicTaskManager.delete(session, periodic_task)

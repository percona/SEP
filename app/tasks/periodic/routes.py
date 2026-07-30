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
from app.core.utils.iterators import unique_everseen
from app.tasks.crud import TaskManager
from app.tasks.deps import (
    get_executable_task_by_name,
    SessionDep,
    validate_chain_task_names,
)
from app.tasks.periodic.crud import PeriodicTaskManager
from app.tasks.periodic.deps import PeriodicTaskDep
from app.tasks.periodic.models import (
    PeriodicTaskExecuteRequest,
    PeriodicTaskResponse,
    PeriodicTaskUpdate,
)
from app.tasks.periodic.utils import attach_last_run_status

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
    owner: str | None = None,
    enabled: bool | None = None,
) -> list[PeriodicTask]:
    """List all periodic tasks."""
    if owner is None:
        periodic_tasks = await PeriodicTaskManager.list(
            session=session, enabled=enabled
        )
    else:
        tasks_names = [
            task.name
            for task in await TaskManager.list_active(
                session=tasks_session, owner=owner
            )
        ]
        periodic_tasks = await PeriodicTaskManager.list_by_task_names(
            session, *tasks_names, enabled=enabled
        )
    return await attach_last_run_status(tasks_session, periodic_tasks)


@router.get(
    "/{periodic_task_id}",
    dependencies=[IsAuthenticatedDep],
    response_model=PeriodicTaskResponse,
)
async def retrieve_periodic_task(
    periodic_task: PeriodicTaskDep,
    tasks_session: SessionDep,
) -> PeriodicTask:
    """Retrieve a periodic task by ID."""
    await attach_last_run_status(tasks_session, [periodic_task])
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
        unique_chain = list(unique_everseen(updated_chain))

        if updated_task.execute_request:
            updated_task.execute_request.chain_task_names = unique_chain
        updated_chain = unique_chain

    if updated_task.execute_request is None and existing_execution_data:
        updated_task.execute_request = PeriodicTaskExecuteRequest(
            **existing_execution_data
        )
        kwargs_dict = json.loads(updated_task.kwargs)
        kwargs_dict["execution_data"] = existing_execution_data
        updated_task.kwargs = json.dumps(kwargs_dict)
        logger.debug(
            "UPDATE PERIODIC TASK - Reconstructed execute_request and kwargs from existing data"
        )

    effective_chain = updated_chain if updated_chain is not None else existing_chain

    # Validate whenever the effective chain exists and either the chain changed
    # or the effective parent task changed.
    if effective_chain and (
        effective_chain != existing_chain or task_name != existing_kwargs["task_name"]
    ):
        logger.debug(
            "UPDATE PERIODIC TASK - VALIDATING CHAIN (chain or parent changed)"
        )
        await validate_chain_task_names(
            tasks_session,
            effective_chain,
            await get_executable_task_by_name(tasks_session, task_name),
        )
    else:
        logger.debug(
            "UPDATE PERIODIC TASK - SKIPPING CHAIN VALIDATION (effective chain and parent unchanged)"
        )

    logger.debug("Updating periodic task %s", existing_task.id)
    updated = await PeriodicTaskManager.update(session, existing_task, updated_task)
    await attach_last_run_status(tasks_session, [updated])
    return updated


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

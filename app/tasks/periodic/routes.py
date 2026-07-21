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
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.deps import IsAuthenticatedDep
from app.core.celery.deps import CeleryBeatSessionDep
from app.core.utils.date_time import make_datetime_utc
from app.core.utils.iterators import unique_everseen
from app.tasks.crud import TaskHistoryManager, TaskManager
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

router = APIRouter(prefix="/periodic", tags=["periodic", "schedule", "tasks"])

logger = logging.getLogger(__name__)


def _resolve_task_name(periodic_task: PeriodicTask) -> str | None:
    """Return the SEP task name a beat-store schedule runs, or ``None``.

    Mirror :meth:`PeriodicTaskResponse.populate_task_data`: the name comes from
    ``args[0]`` and is overridden by ``kwargs["task_name"]`` when present.

    :param periodic_task: The beat-store row to inspect.
    :return: The resolved SEP task name, or ``None`` when it cannot be derived.
    """
    name: str | None = None
    if periodic_task.args and (args := json.loads(periodic_task.args)):
        name = args[0]
    if periodic_task.kwargs and (kwargs := json.loads(periodic_task.kwargs)):
        name = kwargs.get("task_name", name)
    return name


async def attach_last_run_status(
    tasks_session: AsyncSession, periodic_tasks: list[PeriodicTask]
) -> list[PeriodicTask]:
    """Stamp each schedule's own last-run result onto its beat-store rows.

    Resolve the SEP task name behind every schedule, fetch recent
    system-triggered history points for those names in a single bulk query, then
    attribute to each schedule the earliest point whose ``created_at`` is at or
    after that schedule's ``last_run_at`` -- the beat store records
    ``last_run_at`` when it dispatches, so the schedule's own run is the first
    system row at or after that instant. A schedule that has never run
    (``last_run_at is None``) is forced to ``None``. Correlating on the
    schedule's own dispatch time keeps a later, unrelated system run of the same
    task name (a chain child or connectivity check) from being reported as this
    schedule's result. Two schedules that last ran at the same instant on the
    same task name still resolve to the same point.

    :param tasks_session: The tasks-database session used for the history lookup.
    :param periodic_tasks: The beat-store rows to annotate in place.
    :return: The same rows, each carrying a ``last_run_status`` attribute.
    """
    ran = [
        (task, name, make_datetime_utc(task.last_run_at))
        for task in periodic_tasks
        if (name := _resolve_task_name(task)) and task.last_run_at is not None
    ]
    points = await TaskHistoryManager.recent_system_status_points_by_task_names(
        tasks_session, [name for _, name, _ in ran]
    )
    for task in periodic_tasks:
        task.last_run_status = None
    for task, name, run_at in ran:
        task.last_run_status = next(
            (
                point.status
                for point in points.get(name, ())
                if make_datetime_utc(point.created_at) >= run_at
            ),
            None,
        )
    return periodic_tasks


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
    (annotated,) = await attach_last_run_status(tasks_session, [periodic_task])
    return annotated


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
    (annotated,) = await attach_last_run_status(tasks_session, [updated])
    return annotated


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

"""Provide task execution management for Nomad jobs."""

import json
import logging
import time
from asyncio import sleep
from datetime import datetime
from datetime import UTC
from uuid import uuid1

import nomad
from sqlmodel.ext.asyncio.session import AsyncSession

from app.tasks.crud import TaskHistoryManager
from app.tasks.models import Task
from app.tasks.models import TaskHistory
from app.tasks.models import TaskHistoryStatusEnum

__all__ = ["Executor"]


logger = logging.getLogger(__name__)


# TODO: Pydantic
class Executor:
    """Manage the execution of tasks on a Nomad backend.

    The `Executor` class handles task execution for jobs, interacting with the
    Nomad backend. It manages job creation, status tracking, and updating task history.

    :param backend: The Nomad client used for interacting with the backend.
    :type backend: nomad.Nomad
    :param task: The task to be executed.
    :type task: Task
    """

    backend: nomad.Nomad
    task: Task

    def __init__(
        self,
        cfg: dict,
        task: Task,
    ) -> None:
        self.backend = nomad.Nomad(**cfg)
        self.task = task

    async def run(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
        interval: int,
    ) -> TaskHistory:
        """Run a task on the Nomad backend and update task history.

        This method executes the task on the Nomad backend, handles job creation and
        tracking, and updates the task's execution history with logs, states, and
        timing information.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        :param interval: The interval (in seconds) for checking the status of the job.
        :type interval: int
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        :raises ValueError: If the job or job status cannot be determined.
        :raises NotImplementedError: If the job type or certain Nomad features are not
            yet supported.
        """
        job = {}
        status = {}

        # TODO: determine scenarios for execution, such as looking up an existing job
        if queue_item.execution_request.meta:
            # TODO: target is currently pushed in to meta
            queue_item.execution_request.meta["target"] = (
                queue_item.execution_request.target
            )
            # TODO: DC is currently forced
            queue_item.execution_request.meta["dc"] = "dc1"
            # TODO: allow templates in more fields, currently only for constraints
            for meta_var, meta_val in queue_item.execution_request.meta.items():
                for i, constraint in enumerate(self.task.data["Constraints"]):
                    meta = "${NOMAD_META_" + meta_var + "}"
                    self.task.data["Constraints"][i] = json.loads(
                        json.dumps(constraint).replace(meta, meta_val),
                    )

        try:
            new_job = False

            match self.task.data.get("ParameterizedJob"):
                # TODO: temporary to avoid ParameterizedJobs
                case True:
                    raise NotImplementedError("Parameterized job support is TBD")
                case _:
                    match self.task.data.get("Type"):
                        case "batch" | "system" | "sysbatch":
                            new_job = True
                        case _:
                            raise NotImplementedError(
                                f"{self.task.data.get('Type')} job support is TBD",
                            )
        except nomad.api.exceptions.URLNotFoundNomadException:
            logger.debug("Unable to match job, creating a new one")
            new_job = True
        except nomad.api.exceptions.BaseNomadException:
            logger.error("Failed to process job for %s", self.task.name, exc_info=True)
            raise

        start_ts, stop_ts = time.time_ns(), None
        if new_job:
            match self.task.data.get("Type"):
                case "batch" | "system" | "sysbatch":
                    self.task.data["ID"] += f"-{uuid1()}"
                case _:
                    raise NotImplementedError(
                        f"{self.task.data.get('Type')} job support is TBD",
                    )

            status = self.backend.job.register_job(
                id_=self.task.data["ID"],
                job={"Job": self.task.data},
            )
            logger.debug("Job status: %r", status)
            job = self.backend.job.get_job(self.task.data["ID"])
        if not job:
            logger.error("Unable to determine job")
            raise ValueError("The job could not be determined")
        if not status:
            logger.error("Unable to determine status")
            raise ValueError("The job status could not be determined")

        queue_item.execution_request.tracking.update(evaluation_id=status["EvalID"])
        queue_item = await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

        allocation_filters = [
            f'JobID == "{job["ID"]}"',
            f'EvalID == "{status["EvalID"]}"',
        ]
        allocations = self.backend.allocations.get_allocations(
            filter_=" and ".join(allocation_filters),
        )
        logger.debug("Job: %r", job)
        logger.debug("Allocations: %r", [x["JobID"] for x in allocations])

        queue_item.status = TaskHistoryStatusEnum.RUNNING
        queue_item = await TaskHistoryManager.save(session, queue_item)

        alloc = {}
        task_logs = {}
        task_states = {}
        attempts = 0
        while allocations:
            match job["Type"]:
                case "service":
                    raise NotImplementedError("Service job support is TBD")
                case "batch" | "system" | "sysbatch":
                    alloc = allocations[0]
                    task_states[alloc["EvalID"]] = alloc["TaskStates"]
                    task_logs.setdefault(alloc["EvalID"], {})
                    if alloc["TaskStates"]:
                        for step in alloc["TaskStates"]:
                            try:
                                task_logs[alloc["EvalID"]][step] = {
                                    "allocation_id": alloc["ID"],
                                    "stdout": self.backend.client.stream_logs.stream(
                                        alloc["ID"],
                                        task=step,
                                        type_="stdout",
                                    ),
                                    "stderr": self.backend.client.stream_logs.stream(
                                        alloc["ID"],
                                        task=step,
                                        type_="stderr",
                                    ),
                                }
                            except nomad.api.exceptions.BaseNomadException:
                                task_logs[alloc["EvalID"]][step] = {
                                    "allocation_id": alloc["ID"],
                                    "stdout": None,
                                    "stderr": None,
                                }
                case _:
                    raise NotImplementedError(f'Unrecognized job type "{job["Type"]}"')
            match alloc["ClientStatus"]:
                case "complete" | "failed":
                    if alloc["FollowupEvalID"]:
                        allocations = self.backend.allocations.get_allocations(
                            filter_=f'EvalID == "{alloc["FollowupEvalID"]}"',
                        )
                        continue
                    stop_ts = time.time_ns()
                    break
                case _:
                    allocations = self.backend.allocations.get_allocations(
                        filter_=" and ".join(allocation_filters),
                    )
            attempts += 1
            logger.debug("Attempt %d found status %s", attempts, alloc["ClientStatus"])
            await sleep(interval)

        match alloc["ClientStatus"]:
            case "complete":
                queue_item.status = TaskHistoryStatusEnum.SUCCESS
            case _:
                queue_item.status = TaskHistoryStatusEnum.FAILED

        queue_item.execution_request.tracking.update(
            task_states=task_states,
            task_logs=task_logs,
            duration=((stop_ts - start_ts) / 1000**3) - (attempts * interval),
            raw_duration=(stop_ts - start_ts) / 1000**3,
            started_at_ns=start_ts,
            finished_at_ns=stop_ts,
            started_at=datetime.fromtimestamp(start_ts / 1000**3, tz=UTC),
            finished_at=datetime.fromtimestamp(stop_ts / 1000**3, tz=UTC),
        )
        return await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

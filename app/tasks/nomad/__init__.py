"""Nomad"""

import json
import logging
import time
from asyncio import sleep
from datetime import datetime
from datetime import timezone
from uuid import uuid1

import nomad
from app.core.db import Database
from app.core.db import get_timestamp
from app.tasks.models import history
from app.tasks.models import Task
from app.tasks.models import TASK_HISTORY_STATUS_MAP
from app.tasks.models import TaskExecutionRequest

__all__ = ["Executor"]


logger = logging.getLogger(__name__)


class Executor:
    backend: nomad.Nomad
    database: Database
    execution_request: TaskExecutionRequest
    task: Task

    def __init__(
        self,
        cfg: dict,
        database: Database,
        execution_request: TaskExecutionRequest,
        task: Task,
    ) -> None:
        """Configure the executor

        :param cfg:
        :param database:
        :param execution_request:
        :param task:
        :return:
        """
        self.backend = nomad.Nomad(**cfg)
        self.database = database
        self.execution_request = execution_request
        self.task = task

    async def run(self, queue_item: dict, interval: int) -> (dict, int):
        job = {}
        queue_id = queue_item["id"]
        status = {}

        # TODO: determine scenarios for execution, such as looking up an existing job
        task_data = json.loads(self.task.data)
        if queue_item["execution_request"].get("meta"):
            # TODO: target is currently pushed in to meta
            queue_item["execution_request"]["meta"]["target"] = queue_item[
                "execution_request"
            ]["target"]
            # TODO: DC is currently forced
            queue_item["execution_request"]["meta"]["dc"] = "dc1"
            # TODO: allow templates in more fields, currently only for constraints
            for meta_var, meta_val in queue_item["execution_request"]["meta"].items():
                for i, constraint in enumerate(task_data["Constraints"]):
                    meta = "${NOMAD_META_" + meta_var + "}"
                    task_data["Constraints"][i] = json.loads(
                        json.dumps(constraint).replace(meta, meta_val)
                    )

        try:
            new_job = False

            match task_data.get("ParameterizedJob"):
                # TODO: temporary to avoid ParameterizedJobs
                case True:
                    # Example content:
                    # "ParameterizedJob": {"MetaOptional": ["args", "image"],
                    #                       "MetaRequired": ["command"], "Payload": ""}
                    # https://python-nomad.readthedocs.io/en/latest/api/job/#dispatch-job
                    raise NotImplementedError("Parameterized job support is TBD")
                    # if not self.backend.jobs.get_jobs(filter_=f'Name == "{task_data.Name}"'):
                    #    raise nomad.api.exceptions.URLNotFoundNomadException(f"{task_data.Name} could not be found")
                case _:
                    match task_data.get("Type"):
                        case "batch" | "system" | "sysbatch":
                            new_job = True
                        case _:
                            raise NotImplementedError(
                                f"{task_data.get("Type")} job support is TBD"
                            )
        except nomad.api.exceptions.URLNotFoundNomadException:
            logger.debug("Unable to match job, creating a new one")
            new_job = True
        except nomad.api.exceptions.BaseNomadException:
            logger.error("Failed to process job for %s", self.task.name, exc_info=True)
            raise

        start_ts, stop_ts = time.time_ns(), None
        if new_job:
            match task_data.get("Type"):
                case "batch" | "system" | "sysbatch":
                    task_data["ID"] += f"-{uuid1()}"
                case _:
                    raise NotImplementedError(
                        f"{task_data.get("Type")} job support is TBD"
                    )

            status = self.backend.job.register_job(
                id_=task_data.ID, job={"Job": task_data}
            )
            logger.debug("Job status: %r", status)
            job = self.backend.job.get_job(task_data["ID"])
        if not job:
            logger.error("Unable to determine job")
            raise ValueError("The job could not be determined")
        if not status:
            logger.error("Unable to determine status")
            raise ValueError("The job status could not be determined")

        self.execution_request.tracking.update(evaluation_id=status["EvalID"])
        async with self.database.engine.begin() as conn:
            await conn.execute(
                history.update()
                .where(history.c.id == queue_id)
                .values(execution_request=self.execution_request),
            )

        allocation_filters = [
            f'JobID == "{job["ID"]}"',
            f'EvalID == "{status["EvalID"]}"',
        ]
        allocations = self.backend.allocations.get_allocations(
            filter_=" and ".join(allocation_filters)
        )
        logger.debug("Job: %r", job)
        logger.debug("Allocations: %r", [x["JobID"] for x in allocations])

        async with self.database.engine.begin() as conn:
            await conn.execute(
                history.update()
                .where(history.c.id == queue_id)
                .values(
                    status=TASK_HISTORY_STATUS_MAP["running"],
                    updated_at=get_timestamp(),
                ),
            )

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
                        filter_=" and ".join(allocation_filters)
                    )
            attempts += 1
            logger.debug("Attempt %d found status %s", attempts, alloc["ClientStatus"])
            await sleep(interval)

        match alloc["ClientStatus"]:
            case "complete":
                status = TASK_HISTORY_STATUS_MAP["success"]
            case _:
                status = TASK_HISTORY_STATUS_MAP["failed"]

        self.execution_request.tracking.update(
            task_states=task_states,
            task_logs=task_logs,
            duration=((stop_ts - start_ts) / 1000**3) - (attempts * interval),
            raw_duration=(stop_ts - start_ts) / 1000**3,
            started_at_ns=start_ts,
            finished_at_ns=stop_ts,
            started_at=datetime.fromtimestamp(start_ts / 1000**3, tz=timezone.utc),
            finished_at=datetime.fromtimestamp(stop_ts / 1000**3, tz=timezone.utc),
        )
        return self.execution_request, status

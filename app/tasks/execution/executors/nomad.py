"""Provide task execution management for Nomad jobs."""

import json
import logging
import time
from asyncio import sleep
from datetime import datetime, UTC
from functools import cached_property
from typing import Any
from uuid import uuid1

from fastapi import HTTPException, status
from nomad import Nomad
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException
from pydantic import HttpUrl
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.exceptions import HTTPBadRequestException
from app.core.fields import RelativeFilePath
from app.core.utils import async_run, b64encode_str, minify_file_content
from app.tasks.crud import TaskHistoryManager
from app.tasks.execution.models import BaseExecutor
from app.tasks.models import Task, TaskHistory, TaskHistoryStatusEnum

logger = logging.getLogger(__name__)


class NomadExecutor(BaseExecutor):
    """Represent a Nomad task executor.

    :param wait_interval: The interval in seconds between status checks.
        Defaults to 5 seconds.
    :type wait_interval: int
    :param endpoint: The URL for the Nomad API endpoint.
    :type endpoint: HttpUrl
    :param secure: Whether to use a secure connection. Defaults to False.
    :type secure: bool
    :param timeout: The timeout in seconds for requests to the Nomad API.
        Defaults to 10 seconds.
    :type timeout: int
    :param verify: Whether to verify SSL certificates. Can be a file path to the SSL
        certificate. Defaults to False.
    :type verify: bool | RelativeFilePath
    :param cert: SSL certificate and key paths, or a single certificate file path.
        Defaults to an empty tuple.
    :type cert: tuple[RelativeFilePath, RelativeFilePath] | RelativeFilePath
    :param minify_payload: Whether to minify payloads before dispatching Parameterized
        Jobs. Defaults to True.
    :type minify_payload: bool
    """

    endpoint: HttpUrl
    secure: bool = False
    timeout: int = 10
    verify: bool | RelativeFilePath = False
    cert: tuple[RelativeFilePath, RelativeFilePath] | RelativeFilePath = ()
    minify_payload: bool = True

    @cached_property
    def backend(self) -> Nomad:
        """Get the Nomad backend client.

        :return: An instance of the Nomad client configured with the executor's
            settings.
        :rtype: Nomad
        """
        return Nomad(
            address=self.endpoint,
            secure=self.secure,
            timeout=self.timeout,
            verify=self.verify,
            cert=self.cert,
        )

    @staticmethod
    def prepare_task(queue_item: TaskHistory) -> Task:
        """Prepare a Task instance for execution.

        Modify the task data based on the execution request's metadata, such as setting
        target and datacenter information, and applying any necessary template
        substitutions.

        :param queue_item: The task history record containing the task to prepare.
        :type queue_item: TaskHistory
        :return: The prepared `Task` instance ready for execution.
        :rtype: Task
        """
        task = queue_item.task
        # TODO: determine scenarios for execution, such as looking up an existing job  # noqa: TD002, TD003
        task.data["ID"] += f"-{queue_item.execution_request.target}"
        if queue_item.execution_request.meta:
            # TODO: target is currently pushed in to meta  # noqa: TD002, TD003
            queue_item.execution_request.meta["target"] = (
                queue_item.execution_request.target
            )
            # TODO: allow templates in more fields, currently only for constraints  # noqa: TD002, TD003
            for meta_var, meta_val in queue_item.execution_request.meta.items():
                for i, constraint in enumerate(task.data["Constraints"]):
                    meta = "${NOMAD_META_" + meta_var + "}"
                    task.data["Constraints"][i] = json.loads(
                        json.dumps(constraint).replace(meta, meta_val),
                    )
        return task

    def register_job(self, task: Task) -> dict[str, Any]:
        """Register a new job with the Nomad backend.

        Sends the job specification to Nomad for registration. Raises an error if the
        job status cannot be determined.

        :param task: The task to register as a job.
        :type task: Task
        :return: The status response from Nomad after registering the job.
        :rtype: dict[str, Any]
        :raises ValueError: If the job status cannot be determined.
        """
        job_status = self.backend.job.register_job(
            id_=task.data["ID"],
            job={"Job": task.data},
        )
        if not job_status:
            logger.error("Unable to determine status for task %s", task.id)
            raise ValueError("The job status could not be determined")
        return job_status

    def dispatch_job(self, queue_item: TaskHistory) -> dict[str, Any]:
        """Dispatch a parameterized job for execution.

        :param queue_item: The task history containing information about the execution.
        :type queue_item: TaskHistory
        :return: The status response from Nomad after dispatching the job.
        :rtype: dict[str, Any]
        """
        logger.debug("Dispatching job: %s", queue_item)
        payload = queue_item.execution_request.payload_content
        if payload is not None:
            if self.minify_payload:
                payload = minify_file_content(payload)
            payload = b64encode_str(payload)
        job_status = self.backend.job.dispatch_job(
            queue_item.task.data["ID"],
            payload=payload,
            meta=queue_item.execution_request.meta,
        )
        if not job_status:
            logger.error("Unable to dispatch task %s", queue_item.task.id)
            raise ValueError("The job status could not be determined")
        return job_status

    def get_job(self, job_id: str) -> dict[str, Any]:
        """Retrieve a job's details from the Nomad backend.

        Fetches the job information based on the task's ID. Raises an error if the job
        cannot be retrieved.

        :param job_id: The ID of the job to be retrieved.
        :type job_id: str
        :return: The job details retrieved from Nomad.
        :rtype: dict[str, Any]
        :raises ValueError: If the job could not be determined.
        """
        job = self.backend.job.get_job(job_id)
        if not job:
            logger.error("Unable to find job %s", job_id)
            raise ValueError("The job could not be determined")
        return job

    async def run(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
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
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        :raises ValueError: If the job or job status cannot be determined.
        :raises NotImplementedError: If the job type or certain Nomad features are not
            yet supported.
        """
        task = self.prepare_task(queue_item)

        start_ts, stop_ts = time.time_ns(), None
        job_status = {}
        if self.task_needs_new_job(task):
            if not task.data.get("ParameterizedJob"):
                match task.data.get("Type"):
                    case "batch" | "system" | "sysbatch":
                        task.data["ID"] += f"-{uuid1()}"
                    case _:
                        raise NotImplementedError(
                            f"{task.data.get('Type')} job support is TBD",
                        )
            job_status = self.register_job(task)
            logger.debug("Job status: %r", job_status)
            job = self.get_job(task.data["ID"])
            logger.debug("Job: %s", job)
        if task.data.get("ParameterizedJob"):
            job_status = self.dispatch_job(queue_item)
            job = self.get_job(job_status["DispatchedJobID"])

        queue_item.execution_request.tracking.update(evaluation_id=job_status["EvalID"])
        queue_item = await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

        queue_item.status = TaskHistoryStatusEnum.RUNNING
        queue_item = await TaskHistoryManager.save(session, queue_item)

        queue_item = await self.wait_for_job_completion(
            job,
            queue_item,
            job_status["EvalID"],
        )
        stop_ts = time.time_ns()
        queue_item.execution_request.tracking.update(
            raw_duration=(stop_ts - start_ts) / 1000**3,
            started_at_ns=start_ts,
            finished_at_ns=stop_ts,
            started_at=datetime.fromtimestamp(start_ts / 1000**3, tz=UTC),
            finished_at=datetime.fromtimestamp(stop_ts / 1000**3, tz=UTC),
        )
        queue_item.execution_request.tracking["duration"] = (
            (stop_ts - start_ts) / 1000**3
        ) - queue_item.execution_request.tracking["duration"]
        return await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

    async def wait_for_job_completion(
        self,
        job: dict[str, Any],
        queue_item: TaskHistory,
        eval_id: str,
    ) -> TaskHistory:
        """Monitor and wait for a Nomad job to complete.

        Continuously checks the status of the job until it reaches a terminal state,
        updating the task history with logs and states along the way.

        :param job: The job details retrieved from Nomad.
        :type job: dict[str, Any]
        :param queue_item: The task history record to update with job execution details.
        :type queue_item: TaskHistory
        :param eval_id: The evaluation ID associated with the job execution.
        :type eval_id: str
        :return: The updated task history after job completion.
        :rtype: TaskHistory
        :raises NotImplementedError: If the job type is not supported.
        """
        allocation_filters = [
            f'JobID == "{job["ID"]}"',
            f'EvalID == "{eval_id}"',
        ]
        allocations = self.backend.allocations.get_allocations(
            filter_=" and ".join(allocation_filters),
        )
        logger.debug("Allocations: %r", [x["JobID"] for x in allocations])

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
                                        plain=True,
                                    ),
                                    "stderr": self.backend.client.stream_logs.stream(
                                        alloc["ID"],
                                        task=step,
                                        type_="stderr",
                                        plain=True,
                                    ),
                                }
                            except BaseNomadException:
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
                    break
                case _:
                    allocations = self.backend.allocations.get_allocations(
                        filter_=" and ".join(allocation_filters),
                    )
            attempts += 1
            logger.debug("Attempt %d found status %s", attempts, alloc["ClientStatus"])
            await sleep(self.wait_interval)

        match alloc["ClientStatus"]:
            case "complete":
                queue_item.status = TaskHistoryStatusEnum.SUCCESS
            case _:
                queue_item.status = TaskHistoryStatusEnum.FAILED

        queue_item.execution_request.tracking.update(
            task_states=task_states,
            task_logs=task_logs,
            duration=attempts * self.wait_interval,
        )
        return queue_item

    def task_needs_new_job(self, task: Task) -> bool:
        """Determine whether a new job needs to be created for the task.

        Checks the task's configuration to decide if a new job should be registered.

        :param task: The task to evaluate.
        :type task: Task
        :return: `True` if a new job needs to be created, otherwise `False`.
        :rtype: bool
        :raises NotImplementedError: If the task's parameterized job feature or job type
            is not supported.
        :raises BaseNomadException: If there is an issue communicating with the Nomad
            backend.
        """
        if task.data.get("ParameterizedJob"):
            try:
                self.get_job(task.data["ID"])
            except (ValueError, URLNotFoundNomadException):
                return True
            return False
        match task.data.get("Type"):
            case "batch" | "system" | "sysbatch":
                return True
            case _:
                raise NotImplementedError(
                    f"{task.data.get('Type')} job support is TBD",
                )

    # TODO: Use pydantic models instead of dict for job validation  # noqa: TD002, TD003
    async def validate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Validate a Nomad job specification.

        This function sends a job specification to the Nomad backend for validation.
        If validation fails, it raises an HTTPException with the corresponding status code.

        :param job: The Nomad job specification to validate.
        :type job: dict[str, Any]
        :return: The original job specification if validation is successful.
        :rtype: dict[str, Any]
        :raises HTTPException: If validation fails or Nomad returns an error status
            code.
        """
        valid = await async_run(self.backend.validate.validate_job, {"Job": job})
        if valid[0].status_code != status.HTTP_200_OK:
            raise HTTPException(status_code=valid[0].status_code)
        resp = json.loads(valid[0].text)
        if not resp.get("ValidationErrors", []):
            return job
        logger.error(valid[0].text)
        raise HTTPBadRequestException("Invalid job specification")

    def get_hosts(self) -> dict[str, str]:
        """Get healthy node names from Nomad backend.

        :return: A dictionary with node addresses as key and the respective node names
            as values.
        :rtype: dict[str, str]
        """
        filter_expression = "Status == ready and raw_exec in Drivers and Drivers.raw_exec.Healthy == true"
        return {
            node["Address"]: node["Name"]
            for node in self.backend.nodes.get_nodes(filter_=filter_expression)
        }

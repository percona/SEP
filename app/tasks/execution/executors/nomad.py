"""Provide task execution management for Nomad jobs."""

import asyncio
import json
import logging
import time
from binascii import b2a_base64
from collections.abc import AsyncGenerator
from datetime import datetime, UTC
from functools import cached_property
from typing import Any
from uuid import uuid1

from aiohttp import (
    ClientError,
    ClientTimeout,
    SocketTimeoutError,
)
from fastapi import HTTPException, status
from nomad import Nomad
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadRequestException
from app.core.requests import BaseRemoteAPI
from app.core.utils import async_run, sort_dict
from app.tasks.crud import TaskHistoryManager
from app.tasks.execution.models import BaseExecutor
from app.tasks.execution.utils import gzip_compress, minify_file_content
from app.tasks.models import Task, TaskHistory, TaskHistoryStatusEnum, TaskLog

logger = logging.getLogger(__name__)


class NomadExecutor(BaseExecutor, BaseRemoteAPI):
    """Represent a Nomad task executor.

    :param wait_interval: The interval in seconds between status checks.
        Defaults to 5 seconds.
    :type wait_interval: int
    :param endpoint: The base URL for the external API endpoint.
    :type endpoint: HttpUrl
    :param verify_ssl: Whether to verify SSL certificates. Defaults to True.
    :type verify_ssl: bool
    :param ssl_cafile: Path to the SSL certificate authority file. Defaults to None.
    :type ssl_cafile: RelativeFilePath | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePath | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePath | None
    :param logger_name: Name to use for the logger. Defaults to `__name__`.
    :type logger_name: str
    :param secure: Whether to use a secure connection. Defaults to False.
    :type secure: bool
    :param timeout: The timeout in seconds for requests to the Nomad API.
        Defaults to 10 seconds.
    :type timeout: int
    :param minify_payload: Whether to minify payloads before dispatching Parameterized
        Jobs. Defaults to True.
    :type minify_payload: bool
    :param log_socket_read_timeout: Socket read timeout in seconds for log streaming.
            Defaults to 10.
    :type log_socket_read_timeout: int
    """

    secure: bool = False
    timeout: int = 10
    minify_payload: bool = True
    log_socket_read_timeout: int = 10

    @cached_property
    def backend(self) -> Nomad:
        """Get the Nomad backend client.

        :return: An instance of the Nomad client configured with the executor's
            settings.
        :rtype: Nomad
        """
        cert = ()
        if self.ssl_certfile:
            if self.ssl_keyfile:
                cert = (self.ssl_certfile, self.ssl_keyfile)
            else:
                cert = (self.ssl_certfile,)
        return Nomad(
            address=self.endpoint,
            secure=self.secure,
            timeout=self.timeout,
            verify=(self.secure and self.verify_ssl and self.ssl_cafile)
            or self.verify_ssl,
            cert=cert,
        )

    @staticmethod
    def prepare_task(queue_item: TaskHistory, task: Task | None = None) -> Task:
        """Prepare a Task instance for execution.

        Modify the task data based on the execution request's metadata, such as setting
        target and datacenter information, and applying any necessary template
        substitutions.

        :param queue_item: The task history record containing the task to prepare.
        :type queue_item: TaskHistory
        :param task: The task to be executed. If None, the queue_item's task will be
            used.
        :type task: Task | None
        :return: The prepared `Task` instance ready for execution.
        :rtype: Task
        """
        task = queue_item.task if task is None else task
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

    def dispatch_job(
        self, queue_item: TaskHistory, task: Task | None = None
    ) -> dict[str, Any]:
        """Dispatch a parameterized job for execution.

        :param queue_item: The task history containing information about the execution.
        :type queue_item: TaskHistory
        :param task: The task to be executed. If None, the queue_item's task will be
            used.
        :type task: Task | None
        :return: The status response from Nomad after dispatching the job.
        :rtype: dict[str, Any]
        """
        task = queue_item.task if task is None else task
        logger.debug("Dispatching job: %s", queue_item)
        payload = queue_item.execution_request.payload_content
        if payload is not None:
            if self.minify_payload:
                payload = minify_file_content(payload)
            payload = b2a_base64(gzip_compress(payload)).decode("utf-8")
        job_status = self.backend.job.dispatch_job(
            task.data["ID"],
            payload=payload,
            meta=queue_item.execution_request.meta,
        )
        if not job_status:
            logger.error("Unable to dispatch task %s", task.id)
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

    def get_allocation(self, job_id: str, eval_id: str) -> dict[str, Any]:
        """Retrieve a specific allocation for a job evaluation.

        Fetches allocation details based on the job ID and evaluation ID.
        Sorts task states for consistency.

        :param job_id: The ID of the job.
        :type job_id: str
        :param eval_id: The evaluation ID associated with the job.
        :type eval_id: str
        :return: The allocation details from Nomad.
        :rtype: dict[str, Any]
        :raises IndexError: If no allocations are found.
        """
        allocation_filters = [
            f'JobID == "{job_id}"',
            f'EvalID == "{eval_id}"',
        ]
        allocations = self.backend.allocations.get_allocations(
            filter_=" and ".join(allocation_filters),
        )
        logger.debug("Allocations: %r", [alloc["JobID"] for alloc in allocations])
        alloc = allocations[0]
        if alloc["TaskStates"]:
            alloc["TaskStates"] = sort_dict(
                alloc["TaskStates"],
                lambda item: (
                    item[1]["StartedAt"] or "9",
                    item[1]["FinishedAt"] or "9",
                    item[0],
                ),
            )
        return alloc

    async def run(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
        task: Task | None = None,
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
        :param task: The task to be executed. If None, the queue_item's task will be
            used.
        :type task: Task | None
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        :raises ValueError: If the job or job status cannot be determined.
        :raises NotImplementedError: If the job type or certain Nomad features are not
            yet supported.
        """
        task = self.prepare_task(queue_item, task)

        start_ts, stop_ts = time.time_ns(), None
        job_status = {}
        job = None
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
            job_status = self.dispatch_job(queue_item, task)
            job = self.get_job(job_status["DispatchedJobID"])
        if job is None:
            raise ValueError("The job could not be determined")

        queue_item.execution_request.tracking.update(
            evaluation_id=job_status["EvalID"], job_id=job["ID"]
        )
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
        task_logs = {}
        task_states = {}
        attempts = 0
        alloc = self.get_allocation(job["ID"], eval_id)
        while alloc:
            match job["Type"]:
                case "service":
                    raise NotImplementedError("Service job support is TBD")
                case "batch" | "system" | "sysbatch":
                    task_states = alloc["TaskStates"]
                    if task_states:
                        for step in task_states:
                            try:
                                task_logs[step] = {
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
                                task_logs[step] = {
                                    "allocation_id": alloc["ID"],
                                    "stdout": None,
                                    "stderr": None,
                                }
                case _:
                    raise NotImplementedError(f'Unrecognized job type "{job["Type"]}"')
            match alloc["ClientStatus"]:
                case "complete" | "failed":
                    if alloc["FollowupEvalID"]:
                        alloc = self.get_allocation(job["ID"], alloc["FollowupEvalID"])
                        continue
                    break
                case _:
                    alloc = self.get_allocation(job["ID"], eval_id)
            attempts += 1
            logger.debug("Attempt %d found status %s", attempts, alloc["ClientStatus"])
            await asyncio.sleep(self.wait_interval)

        match alloc["ClientStatus"]:
            case "complete":
                queue_item.status = TaskHistoryStatusEnum.SUCCESS
            case _:
                queue_item.status = TaskHistoryStatusEnum.FAILED

        queue_item.execution_request.tracking.update(
            task_states=task_states,
            task_logs=sort_dict(
                task_logs, lambda item: list(task_states.keys()).index(item[0])
            ),
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

    async def _push_logs_to_queue(
        self,
        # TODO(yan): Use Pydantic model for alloc
        # SEP-154
        alloc: dict[str, Any],
        step: str,
        log_type: str,
        queue: asyncio.Queue,
    ) -> None:
        """Push logs to the asynchronous queue for processing.

        :param alloc: The allocation details containing the task states.
        :type alloc: dict[str, Any]
        :param step: The task step name.
        :type step: str
        :param log_type: The type of log to stream ('stdout' or 'stderr').
        :type log_type: str
        :param queue: The asyncio queue to push log lines into.
        :type queue: asyncio.Queue
        """
        timeout = ClientTimeout(sock_read=self.log_socket_read_timeout)
        params = {
            "task": step,
            "type": log_type,
            "plain": "true",
            "follow": "true",
        }
        state = "running"
        while state == "running":
            alloc_id = alloc["ID"]
            try:
                logger.debug("Requesting logs for %s with params %s", alloc_id, params)
                async with self._request(
                    "GET",
                    f"/v1/client/fs/logs/{alloc_id}",
                    params=params,
                    timeout=timeout,
                ) as response:
                    logger.debug("Log response status: %s", response.status)
                    if (
                        response.status == status.HTTP_404_NOT_FOUND
                        and alloc["TaskStates"][step]["StartedAt"] is None
                    ):
                        logger.info(
                            "Task %s of alloc %s has not started yet. Retrying in %s seconds...",
                            step,
                            alloc_id,
                            self.wait_interval,
                        )
                        await asyncio.sleep(self.wait_interval)
                        continue
                    response.raise_for_status()
                    async for line in response.content:
                        await queue.put(
                            TaskLog(step=step, type=log_type, msg=line.decode("utf-8"))
                        )
            except SocketTimeoutError:
                logger.info(
                    "Timeout occurred while fetching %s logs for %s (%s)",
                    log_type,
                    step,
                    alloc_id,
                )
                alloc = self.get_allocation(alloc["JobID"], alloc["EvalID"])
                state = alloc["TaskStates"][step]["State"]
            except ClientError:
                logger.exception(
                    "An error occurred while fetching %s logs for %s (%s)",
                    log_type,
                    step,
                    alloc_id,
                )
                break
        await queue.put(TaskLog(step=step, type=log_type, msg=None))

    async def stream_logs(
        self, queue_item: TaskHistory
    ) -> AsyncGenerator[TaskLog | None, None]:
        """Stream logs from a task history record.

        Retrieves the allocation details and concurrently streams stdout and stderr logs
        for each task step. Yields `TaskLog` instances as log lines are received.

        :param queue_item: The task history record for tracking the logs.
        :type queue_item: TaskHistory
        :yield: `TaskLog` instances containing log messages.
        :rtype: TaskLog | None
        """
        job_id = queue_item.execution_request.tracking["job_id"]
        eval_id = queue_item.execution_request.tracking["evaluation_id"]
        alloc = self.get_allocation(job_id, eval_id)
        active_streams = set()
        queue = asyncio.Queue()
        push_logs_tasks = []
        task_states = alloc["TaskStates"]
        if task_states:
            for step in set(task_states):
                for log_type in ("stdout", "stderr"):
                    stream = (step, log_type)
                    logger.debug("Adding %s to active_streams", stream)
                    active_streams.add(stream)
                    push_logs_tasks.append(
                        asyncio.create_task(
                            self._push_logs_to_queue(alloc, step, log_type, queue)
                        )
                    )

            while active_streams:
                logger.debug("Waiting for log line for streams %s", active_streams)
                log_line = await queue.get()
                logger.debug("Received log line %s", log_line)
                if log_line.msg is None:
                    stream = (log_line.step, log_line.type)
                    logger.info(
                        "Log stream %s is over, removing it from active_streams",
                        stream,
                    )
                    active_streams.remove(stream)
                    continue
                yield log_line
                queue.task_done()

            await asyncio.gather(*push_logs_tasks)
        else:
            yield None

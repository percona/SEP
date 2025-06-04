"""Provide task execution management for Nomad jobs."""

import asyncio
import json
import logging
from binascii import b2a_base64
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import datetime, UTC
from enum import StrEnum
from functools import cached_property
from itertools import product
from typing import Any
from uuid import uuid1

from aiohttp import (
    ClientError,
    ClientTimeout,
)
from fastapi import HTTPException, status
from nomad import Nomad
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadRequestException
from app.core.requests import BaseRemoteAPI
from app.core.utils import (
    async_run,
    b64decode_str,
    slugify,
    sort_dict,
    utc_now,
)
from app.tasks.crud import TaskHistoryManager
from app.tasks.entity import presidio_anonymize_log
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundException,
    JobNotFoundException,
)
from app.tasks.execution.models import BaseExecutor
from app.tasks.execution.utils import gzip_compress, minify_file_content
from app.tasks.models import (
    Task,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskLogType,
)

logger = logging.getLogger(__name__)


NOMAD_DEAD_JOB_STATUS = "dead"


class NomadAllocStatusEnum(StrEnum):
    """Reproduce Nomad's possible allocation statuses.

    :cvar PENDING: Enum value for pending allocations.
    :vartype PENDING: str
    :cvar RUNNING: Enum value for running allocations.
    :vartype RUNNING: str
    :cvar COMPLETE: Enum value for completed allocations.
    :vartype COMPLETE: str
    :cvar FAILED: Enum value for failed allocations.
    :vartype FAILED: str
    :cvar LOST: Enum value for lost allocations.
    :vartype LOST: str
    :cvar UNKNOWN: Enum value for allocations with unknown status.
    :vartype UNKNOWN: str
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    FAILED = "failed"
    LOST = "lost"
    UNKNOWN = "unknown"


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
    def get_task_history_status_from_alloc_status(
        client_status: NomadAllocStatusEnum,
        default: TaskHistoryStatusEnum | None = None,
        *,
        stopped: bool = False,
    ) -> TaskHistoryStatusEnum | None:
        """Get the task history status based on the allocation status.

        :param client_status: The Nomad allocation status.
        :type client_status: NomadAllocStatusEnum
        :param default: The default status to return if no match is found. Defaults to
            None.
        :type default: TaskHistoryStatusEnum | None
        :param stopped: Whether the Nomad job was stopped.
        :type stopped: bool
        :return: The corresponding task history status.
        :rtype: TaskHistoryStatusEnum | None
        """
        match client_status:
            case NomadAllocStatusEnum.COMPLETE if not stopped:
                return TaskHistoryStatusEnum.SUCCESS
            case NomadAllocStatusEnum.COMPLETE if stopped:
                return TaskHistoryStatusEnum.STOPPED
            case NomadAllocStatusEnum.FAILED:
                return TaskHistoryStatusEnum.FAILED
            case NomadAllocStatusEnum.LOST | NomadAllocStatusEnum.UNKNOWN:
                return TaskHistoryStatusEnum.LOST
            case _:
                return default

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
        task.data["ID"] += f"-{slugify(queue_item.execution_request.target)}"
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
            id_prefix_template=f"{slugify(queue_item.task.name)}-{queue_item.task.id}",
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
        :raises JobNotFoundException: If the job could not be determined.
        """
        try:
            return self.backend.job.get_job(job_id)
        except URLNotFoundNomadException as exc:
            raise JobNotFoundException(exc.nomad_resp) from None

    def get_job_for_task_history(self, queue_item: TaskHistory) -> dict[str, Any]:
        """Retrieve the job associated with a task history record.

        This method checks the task history's tracking information for a job ID and
        retrieves the job details from the Nomad backend. Raises an error if the job ID
        is missing or if the job cannot be found.

        :param queue_item: The task history record for which to fetch the job.
        :type queue_item: TaskHistory
        :return: The job details retrieved from Nomad.
        :rtype: dict[str, Any]
        :raises JobNotFoundException: If the job ID is missing or the job cannot be
            found.
        """
        if job_id := queue_item.execution_request.tracking.get("job_id"):
            return self.get_job(job_id)
        raise JobNotFoundException(
            f"Missing job_id in task history tracking ({queue_item.id})"
        )

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

    def get_allocation_for_task_history(
        self, queue_item: TaskHistory
    ) -> dict[str, Any]:
        """Retrieve the allocation for a task history record.

        This method fetches the allocation details based on the job ID and evaluation ID
        associated with the task history. If an allocation ID is present in the tracking
        information, it retrieves the allocation directly using that ID.

        :param queue_item: The task history record for which to fetch the allocation.
        :type queue_item: TaskHistory
        :return: The allocation details from Nomad.
        :rtype: dict[str, Any]
        :raises AllocationNotFoundException: If allocation cannot be found directly
            through an allocation_id and no allocations are found with the job_id and
            evaluation_id attached to the queue_item.
        """
        if alloc_id := queue_item.execution_request.tracking.get("allocation_id"):
            logger.debug("Fetching allocation %r attached to TaskHistory", alloc_id)
            try:
                return self.backend.allocation.get_allocation(alloc_id)
            except URLNotFoundNomadException:
                logger.debug("Allocation %r not found", alloc_id)
        job_id = queue_item.execution_request.tracking.get("job_id")
        eval_id = queue_item.execution_request.tracking.get("evaluation_id")
        logger.debug(
            "Fetching last allocation for Job ID %s and Eval ID %s", job_id, eval_id
        )
        return self.get_last_allocation(job_id, eval_id)

    def get_last_allocation(
        self, job_id: str | None = None, eval_id: str | None = None
    ) -> dict[str, Any]:
        """Retrieve the last allocation for a job evaluation.

        This method fetches and returns details of the most recent allocation that
        matches the specified job ID and/or evaluation ID filters. Sorts task states for
        consistency.

        :param job_id: The ID of the job.
        :type job_id: str | None
        :param eval_id: The evaluation ID associated with the job.
        :type eval_id: str | None
        :return: The allocation details from Nomad, or None if no allocations are found.
        :rtype: dict[str, Any] | None
        :raises ValueError: If neither job_id nor eval_id is provided.
        :raises AllocationNotFoundException: If no allocations are found with the
            specified filters.
        """
        allocation_filters = []
        if job_id:
            allocation_filters.append(f'JobID == "{job_id}"')
        if eval_id:
            allocation_filters.append(f'EvalID == "{eval_id}"')
        if not allocation_filters:
            raise ValueError("Either job_id or eval_id must be provided")
        allocation_filter = " and ".join(allocation_filters)
        allocations = self.backend.allocations.get_allocations(
            filter_=allocation_filter,
            reverse=True,
        )
        if not allocations:
            raise AllocationNotFoundException(
                f"No allocations found with filter {allocation_filter!r}"
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

    async def dispatch_task(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
        task: Task | None = None,
    ) -> TaskHistory:
        """Dispatch a task on the Nomad backend and update task history.

        This method starts the task on the Nomad backend, handling job creation and
        dispatching, and updates the task's execution history with tracking information.

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

        submit_timestamp = job.get("SubmitTime")
        if submit_timestamp:
            queue_item.started_at = datetime.fromtimestamp(
                submit_timestamp / 10**9, UTC
            )
        else:
            queue_item.started_at = utc_now()
        queue_item.execution_request.tracking.update(
            evaluation_id=job_status["EvalID"], job_id=job["ID"]
        )
        queue_item.status = TaskHistoryStatusEnum.RUNNING
        return await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

    async def stop_task(
        self, session: AsyncSession, queue_item: TaskHistory
    ) -> TaskHistory:
        """Stop a task execution in Nomad.

        This method calls the Nomad API to stop the job associated with the given
        task history. It updates the task history with the status of the operation.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        """
        job_id = queue_item.execution_request.tracking.get("job_id")
        if not job_id:
            raise ValueError("The job ID could not be determined")
        self.backend.job.deregister_job(job_id)
        queue_item = await self.sync_task_history(session, queue_item)
        queue_item.status = TaskHistoryStatusEnum.STOPPED
        queue_item.finished_at = utc_now()
        return await TaskHistoryManager.save(session, queue_item)

    def get_logs_for_allocation(
        self,
        alloc: dict[str, Any],
        anonymize: int | None = None,
        initial_logs: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Get logs for a specific allocation.

        This method retrieves logs for each task step in the allocation and returns a
        dictionary containing the logs and their last offsets.

        :param alloc: The allocation details from Nomad.
        :type alloc: dict[str, Any]
        :param initial_logs: Initial logs to be merged with the fetched logs.
        :type initial_logs: dict[str, dict[str, Any]] | None
        :return: A dictionary containing logs for each task step, including their last
            offsets.
        :rtype: dict[str, dict[str, Any]]
        """
        alloc_id = alloc["ID"]
        task_logs = defaultdict(dict, initial_logs or {})
        if task_states := alloc["TaskStates"]:
            for step, log_type in product(task_states, TaskLogType):
                task_logs[step][log_type] = task_logs[step].get(log_type) or ""
                last_offset_key = f"{log_type}_last_offset"
                task_logs[step][last_offset_key] = (
                    task_logs[step].get(last_offset_key) or 0
                )
                try:
                    raw_log_data = self.backend.client.stream_logs.stream(
                        alloc_id,
                        task=step,
                        type_=log_type,
                        offset=task_logs[step][last_offset_key],
                    )
                except BaseNomadException:
                    logger.exception(
                        "Error while fetching %s logs for allocation %s (step %s)",
                        log_type,
                        alloc_id,
                        step,
                    )
                else:
                    for raw_log_data_item in (
                        "{" + item for item in raw_log_data.split("{") if item
                    ):
                        log_data = json.loads(raw_log_data_item)
                        task_logs[step][last_offset_key] = log_data["Offset"]
                        decoded_data = b64decode_str(log_data["Data"])
                        if step in ("run-script", "step1"):
                            decoded_data = presidio_anonymize_log(
                                decoded_data, anonymize
                            )
                        task_logs[step][log_type] += decoded_data
        return task_logs

    async def sync_task_history(
        self,
        session: AsyncSession,
        queue_item: TaskHistory,
    ) -> TaskHistory:
        """Synchronize the task history with the current state of the task in Nomad.

        This method retrieves the latest allocation details and updates the task history
        with the current status, task states, and logs. If the task is no longer
        running, it updates the status accordingly.

        :param session: The SQLAlchemy asynchronous session to use for database
            operations.
        :type session: AsyncSession
        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        """
        if queue_item.status != TaskHistoryStatusEnum.RUNNING:
            return queue_item

        try:
            alloc = self.get_allocation_for_task_history(queue_item)
            job_id = alloc["JobID"]
            while followup_eval_id := alloc.get("FollowupEvalID"):
                alloc = self.get_last_allocation(job_id, followup_eval_id)
                queue_item.execution_request.tracking.update(
                    task_states={},
                    task_logs={},
                )
        except AllocationNotFoundException:
            logger.debug("Allocation not found for task history %s", queue_item.id)
            try:
                job = self.get_job_for_task_history(queue_item)
                if all(
                    evaluation.get("Status") != NomadAllocStatusEnum.PENDING
                    for evaluation in self.backend.job.get_evaluations(job["ID"])
                ):
                    logger.warning(
                        "No allocations or pending evaluations found for task history %s",
                        queue_item.id,
                    )
                    queue_item.status = TaskHistoryStatusEnum.FAILED
                    queue_item.started_at = None
                    return await TaskHistoryManager.save(
                        session,
                        queue_item,
                        flag_modified_fields=["execution_request"],
                    )

            except JobNotFoundException:
                logger.warning(
                    "Lost job and allocation from task history %s", queue_item.id
                )
                queue_item.status = TaskHistoryStatusEnum.LOST
                return await TaskHistoryManager.save(
                    session,
                    queue_item,
                    flag_modified_fields=["execution_request"],
                )
            return queue_item

        task_states = alloc["TaskStates"]
        task_logs = self.get_logs_for_allocation(
            alloc,
            queue_item.task.anonymize,
            queue_item.execution_request.tracking.get("task_logs", {}),
        )
        logger.debug(
            "sync_task_history(queue_item_id=%s): tasks_logs = %r",
            queue_item.id,
            task_logs,
        )
        queue_item.execution_request.tracking.update(
            allocation_id=alloc["ID"],
            job_id=job_id,
            evaluation_id=alloc["EvalID"],
            task_states=task_states,
            task_logs=sort_dict(
                task_logs, lambda item: list(task_states.keys()).index(item[0])
            ),
        )

        try:
            job = self.get_job(job_id)
        except JobNotFoundException:
            queue_item.status = TaskHistoryStatusEnum.LOST
        else:
            if job["Status"] == NOMAD_DEAD_JOB_STATUS:
                last_modified_timestamp = alloc.get("ModifyTime")
                if last_modified_timestamp:
                    queue_item.finished_at = datetime.fromtimestamp(
                        last_modified_timestamp / 10**9, UTC
                    )
                else:
                    queue_item.finished_at = utc_now()

                queue_item.status = self.get_task_history_status_from_alloc_status(
                    alloc["ClientStatus"],
                    queue_item.status,
                    stopped=job.get("Stop", False),
                )

        return await TaskHistoryManager.save(
            session,
            queue_item,
            flag_modified_fields=["execution_request"],
        )

    async def anonymize_logs(
        self,
        alloc_id: str,
        task_name: str,
        anonymize_config: Any,
        queue_item: TaskHistory,
        task_logs: dict,
    ) -> None:
        """Fetch and anonymize logs for a specific task.

        :param alloc_id: Allocation ID for the task.
        :type alloc_id: str
        :param task_name: Name of the task.
        :type task_name: str
        :param anonymize_config: Configuration for anonymizing logs.
        :type anonymize_config: Any
        :param queue_item: The task history record being updated.
        :type queue_item: TaskHistory
        :param task_logs: Dictionary to store anonymized logs.
        :type task_logs: dict
        """
        try:
            raw_stdout = self.backend.client.stream_logs.stream(
                alloc_id, task=task_name, type_="stdout", plain=True
            )
            raw_stderr = self.backend.client.stream_logs.stream(
                alloc_id, task=task_name, type_="stderr", plain=True
            )
            anonymized_stdout, stdout_items = presidio_anonymize_log(
                raw_stdout, anonymize_config
            )
            anonymized_stderr, stderr_items = presidio_anonymize_log(
                raw_stderr, anonymize_config
            )

            task_logs[task_name] = {
                "allocation_id": alloc_id,
                "stdout": anonymized_stdout,
                "stderr": anonymized_stderr,
            }

            if stdout_items or stderr_items:
                if queue_item.anonymized_items is None:
                    queue_item.anonymized_items = {}

                queue_item.anonymized_items[task_name] = {
                    "stdout": stdout_items or None,
                    "stderr": stderr_items or None,
                }
        except BaseNomadException:
            task_logs[task_name] = {
                "allocation_id": alloc_id,
                "stdout": None,
                "stderr": None,
            }

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
            except JobNotFoundException:
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
        log_type: TaskLogType,
        queue: asyncio.Queue,
    ) -> None:
        """Push logs to the asynchronous queue for processing.

        :param alloc: The allocation details containing the task states.
        :type alloc: dict[str, Any]
        :param step: The task step name.
        :type step: str
        :param log_type: The type of log to stream ('stdout' or 'stderr').
        :type log_type: TaskLogType
        :param queue: The asyncio queue to push log lines into.
        :type queue: asyncio.Queue
        """
        timeout = ClientTimeout(sock_read=self.log_socket_read_timeout)
        params = {
            "task": step,
            "type": log_type,
            "follow": "true",
            "offset": 0,
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
                        logger.debug(
                            "Task %s of alloc %s has not started yet. Retrying in %s seconds...",
                            step,
                            alloc_id,
                            self.wait_interval,
                        )
                        await asyncio.sleep(self.wait_interval)
                        continue
                    response.raise_for_status()
                    empty_data_count = 0
                    raw_data = b""
                    async for chunk, _ in response.content.iter_chunks():
                        raw_data += chunk
                        if b"}" in chunk:
                            data = json.loads(raw_data)
                            raw_data = b""
                            params["offset"] = data.get("Offset", params["offset"])
                            if data and (msg := data.get("Data")):
                                empty_data_count = 0
                                await queue.put(
                                    TaskLog(
                                        step=step, type=log_type, msg=b64decode_str(msg)
                                    )
                                )
                            elif empty_data_count >= self.log_socket_read_timeout:
                                logger.debug(
                                    "No data received for %s seconds, rechecking job status...",
                                    self.log_socket_read_timeout,
                                )
                                alloc = self.get_last_allocation(
                                    alloc["JobID"], alloc["EvalID"]
                                )
                                state = alloc["TaskStates"][step]["State"]
                                break
                            else:
                                empty_data_count += 1
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
        alloc = self.get_last_allocation(job_id, eval_id)
        active_streams = set()
        queue = asyncio.Queue()
        push_logs_tasks = []
        task_states = alloc["TaskStates"]
        if task_states:
            for step in set(task_states):
                for log_type in TaskLogType:
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

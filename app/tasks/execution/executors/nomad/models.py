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

"""Provide task execution management for Nomad jobs."""

import asyncio
import io
import json
import logging
import tarfile
import time
from binascii import b2a_base64
from collections import defaultdict
from collections.abc import AsyncGenerator
from datetime import datetime, UTC
from enum import StrEnum
from functools import cached_property
from itertools import product
from pathlib import Path
from typing import Any

from aiohttp import (
    ClientError,
    ClientTimeout,
)
from fastapi import status
from nomad import Nomad
from nomad.api.exceptions import BaseNomadException, URLNotFoundNomadException
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.exceptions import HTTPBadRequestException
from app.core.requests import BaseRemoteAPI
from app.core.utils import (
    async_run,
    b64decode_str,
    make_datetime_utc,
    slugify,
    sort_dict,
    utc_now,
)
from app.tasks.anonymizer import anonymize_text
from app.tasks.anonymizer.entities import PIIEntity
from app.tasks.crud import TaskHistoryLogStateManager, TaskHistoryManager
from app.tasks.execution.executors.nomad.exceptions import (
    AllocationNotFoundError,
    JobNotFoundError,
)
from app.tasks.execution.models import BaseExecutor
from app.tasks.execution.utils import gzip_compress, minify_file_content
from app.tasks.logs.log_reader import decompress_legacy_logs
from app.tasks.logs.log_writer import (
    backfill_legacy_logs,
    TaskHistoryLogWriter,
)
from app.tasks.models import (
    ExecutionEvent,
    FileMetadata,
    Task,
    TaskHistory,
    TaskHistoryStatusEnum,
    TaskLog,
    TaskLogType,
)

logger = logging.getLogger(__name__)

_ONE_MEBIBYTE = 1024 * 1024
NOMAD_DEAD_JOB_STATUS = "dead"
# Internal states returned by :meth:`NomadExecutor._consume_nomad_log_stream` (not Nomad task states).
_NOMAD_LOG_STREAM_SOCK_TIMEOUT = "nomad-log-stream-sock-timeout"
_NOMAD_LOG_STREAM_CLIENT_ERROR = "nomad-log-stream-client-error"


def _nomad_event_body_text(ev: dict) -> str:
    raw = ev.get("DisplayMessage") or ev.get("Message") or ev.get("Description") or ""
    if isinstance(raw, str):
        return raw.strip()
    return str(raw).strip() if raw else ""


def _nomad_event_exit_code(ev: dict) -> Any:
    exit_code = ev.get("ExitCode")
    details = ev.get("Details")
    if exit_code is None and isinstance(details, dict):
        return details.get("exit_code", details.get("ExitCode"))
    return exit_code


def _append_exit_code_suffix(
    parts: list[str], description: str, exit_code: Any
) -> None:
    desc_lower = description.lower()
    try:
        code_int = int(exit_code)
    except (TypeError, ValueError):
        if str(exit_code).lower() not in desc_lower:
            parts.append(f"(exit code {exit_code})")
        return
    if f"exit code {code_int}" not in desc_lower:
        parts.append(f"(exit code {exit_code})")


def _sortable_nomad_tracking_event(
    task_name: str,
    list_index: int,
    ev: dict,
) -> tuple[datetime, str, int, ExecutionEvent] | None:
    if not isinstance(ev, dict):
        return None
    ts_raw = ev.get("Time")
    try:
        ts_ns = int(ts_raw)
    except (TypeError, ValueError):
        return None

    event_type = ev.get("Type")
    if not isinstance(event_type, str):
        event_type = str(event_type) if event_type is not None else "Unknown"

    description = _nomad_event_body_text(ev)
    parts = []
    parts.append(description if description else event_type)

    exit_code = _nomad_event_exit_code(ev)
    if exit_code is not None:
        _append_exit_code_suffix(parts, description, exit_code)

    dt = NomadExecutor.timestamp_to_datetime(ts_ns)
    return (
        dt,
        task_name,
        list_index,
        ExecutionEvent(
            timestamp=make_datetime_utc(dt),
            event_type=event_type,
            description=" ".join(parts).strip(),
            step=task_name,
        ),
    )


def nomad_task_states_to_execution_events(
    task_states: dict[str, Any] | None,
) -> list[ExecutionEvent]:
    """Map Nomad allocation ``TaskStates`` (from tracking) to execution events.

    Parses each task's ``Events`` array defensively for Nomad API shape drift.

    :param task_states: The ``task_states`` object from execution tracking.
    :type task_states: dict[str, Any] | None
    :return: Events sorted by timestamp ascending (oldest first).
    :rtype: list[ExecutionEvent]
    """
    if not isinstance(task_states, dict):
        return []

    collected = []

    for task_name, state in task_states.items():
        if not isinstance(task_name, str) or not isinstance(state, dict):
            continue
        raw_events = state.get("Events")
        if not isinstance(raw_events, list):
            continue
        for idx, ev in enumerate(raw_events):
            row = _sortable_nomad_tracking_event(task_name, idx, ev)
            if row is not None:
                collected.append(row)

    collected.sort(key=lambda item: (item[0], item[1], item[2]))
    return [item[3] for item in collected]


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
    :type ssl_cafile: RelativeFilePathField | None
    :param ssl_keyfile: Path to the SSL key file. Defaults to None.
    :type ssl_keyfile: RelativeFilePathField | None
    :param ssl_certfile: Path to the SSL certificate file. Defaults to None.
    :type ssl_certfile: RelativeFilePathField | None
    :param logger_name: Name to use for the logger. Defaults to ``__name__``.
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
    def timestamp_to_datetime(timestamp: int) -> datetime:
        """Convert a Nomad timestamp to a datetime object.

        :param timestamp: The Nomad timestamp in nanoseconds.
        :type timestamp: int
        :return: The corresponding datetime object in UTC.
        :rtype: datetime
        """
        return datetime.fromtimestamp(timestamp / 10**9, UTC)

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
        :return: The prepared ``Task`` instance ready for execution.
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
                        json.dumps(constraint).replace(meta, str(meta_val)),
                    )
        return task

    def get_events(self, queue_item: TaskHistory) -> list[ExecutionEvent]:
        """Return task events from stored Nomad ``task_states`` tracking data."""
        tracking = queue_item.execution_request.tracking
        if not isinstance(tracking, dict):
            return []
        return nomad_task_states_to_execution_events(tracking.get("task_states"))

    async def parse_payload(
        self, payload: str | bytes, payload_format: str
    ) -> dict[str, Any]:
        """Parse a job spec payload based on its format.

        This function parses the payload according to the specified format
        (HCL, JSON, or YAML).

        :param payload: The job specification payload to be parsed.
        :type payload: str | bytes
        :param payload_format: The format of the payload, which can be "hcl", "json",
            or "yaml".
        :type payload_format: str
        :return: The parsed job specification.
        :rtype: dict[str, Any]
        :raises ValueError: If the provided payload format is unsupported.
        """
        if payload_format == "hcl":
            return await async_run(self.backend.jobs.parse, payload)
        return await super().parse_payload(payload, payload_format)

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

        filtered_meta = (
            {
                key: value
                for key, value in queue_item.execution_request.meta.items()
                if not key.startswith("_")
            }
            if queue_item.execution_request.meta
            else {}
        )

        custom_prefix = queue_item.execution_request.meta.get("_job_id_prefix", "")
        if custom_prefix:
            custom_prefix = f"-{slugify(custom_prefix)}"

        job_status = self.backend.job.dispatch_job(
            task.data["ID"],
            payload=payload,
            meta=filtered_meta,
            id_prefix_template=f"{slugify(queue_item.task.name)}-{queue_item.task.id}{custom_prefix}",
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
        :raises JobNotFoundError: If the job could not be determined.
        """
        try:
            return self.backend.job.get_job(job_id)
        except URLNotFoundNomadException as exc:
            raise JobNotFoundError(
                str(exc.nomad_resp),
                executor_name="nomad",
                resource_type="job",
                resource_id=job_id,
            ) from None

    def get_job_for_task_history(self, queue_item: TaskHistory) -> dict[str, Any]:
        """Retrieve the job associated with a task history record.

        This method checks the task history's tracking information for a job ID and
        retrieves the job details from the Nomad backend. Raises an error if the job ID
        is missing or if the job cannot be found.

        :param queue_item: The task history record for which to fetch the job.
        :type queue_item: TaskHistory
        :return: The job details retrieved from Nomad.
        :rtype: dict[str, Any]
        :raises JobNotFoundError: If the job ID is missing or the job cannot be
            found.
        """
        if job_id := queue_item.execution_request.tracking.get("job_id"):
            return self.get_job(job_id)
        raise JobNotFoundError(
            f"Missing job_id in task history tracking ({queue_item.id})",
            executor_name="nomad",
            resource_type="job",
        )

    def get_hosts(self) -> dict[str, str]:
        """Get healthy node names from Nomad backend.

        :return: A dictionary with node names as key and the respective addresses
            as values.
        :rtype: dict[str, str]
        """
        filter_expression = "Status == ready and raw_exec in Drivers and Drivers.raw_exec.Healthy == true"
        return {
            node["Name"]: node["Address"]
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
        :raises AllocationNotFoundError: If allocation cannot be found directly
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
        :raises AllocationNotFoundError: If no allocations are found with the
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
            raise AllocationNotFoundError(
                f"No allocations found with filter {allocation_filter!r}",
                executor_name="nomad",
                resource_type="allocation",
                resource_id=allocation_filter,
                job_id=job_id,
                evaluation_id=eval_id,
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
        if self.task_needs_job_register(task):
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
            queue_item.started_at = self.timestamp_to_datetime(submit_timestamp)
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

    async def _stop_task(self, queue_item: TaskHistory) -> None:
        """Stop a task execution in Nomad.

        This method calls the Nomad API to stop the job associated with the given
        task history. It updates the task history with the status of the operation.

        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        """
        job_id = queue_item.execution_request.tracking.get("job_id")
        if not job_id:
            raise ValueError("The job ID could not be determined")
        self.backend.job.deregister_job(job_id)

    def _fetch_step_log_delta(
        self,
        alloc_id: str,
        step: str,
        log_type: TaskLogType,
        start_offset: int,
        anonymize_entities: set[PIIEntity] | None,
    ) -> tuple[str, int]:
        """Fetch the delta bytes and advanced offset for a single step/log_type.

        :param alloc_id: The Nomad allocation identifier.
        :type alloc_id: str
        :param step: The Nomad task name within the allocation.
        :type step: str
        :param log_type: The log stream type (stdout or stderr).
        :type log_type: TaskLogType
        :param start_offset: The byte offset to start reading from in Nomad.
        :type start_offset: int
        :param anonymize_entities: PII entities to anonymize for ``run-script``
            and ``step1`` content. When ``None``, no anonymization is performed.
        :type anonymize_entities: set[PIIEntity] | None
        :return: ``(delta_text, new_offset)`` — the bytes fetched this cycle
            and the producer-relative offset after the fetch.
        :rtype: tuple[str, int]
        """
        try:
            raw_log_data = self.backend.client.stream_logs.stream(
                alloc_id,
                task=step,
                type_=log_type,
                offset=start_offset,
            )
        except BaseNomadException:
            logger.exception(
                "Error while fetching %s logs for allocation %s (step %s)",
                log_type,
                alloc_id,
                step,
            )
            return "", start_offset
        delta = ""
        offset = start_offset
        for raw_log_data_item in (
            "{" + item for item in raw_log_data.split("{") if item
        ):
            log_data = json.loads(raw_log_data_item)
            if raw_msg := log_data.get("Data"):
                offset = log_data.get("Offset", offset)
                msg = b64decode_str(raw_msg)
                if step in ("run-script", "step1") and anonymize_entities:
                    msg = anonymize_text(msg, anonymize_entities)
                delta += msg
        return delta, offset

    def get_logs_for_allocation(
        self,
        alloc: dict[str, Any],
        initial_logs: dict[str, dict[str, Any]] | None = None,
        anonymize_entities: set[PIIEntity] | None = None,
    ) -> dict[str, dict[str, Any]]:
        """Return the delta logs for an allocation since the previous offsets.

        For every ``(step, log_type)`` with a started task state, fetch the
        Nomad log stream starting at the offset provided in ``initial_logs`` (or
        ``0`` when absent). The returned dict holds ONLY the bytes fetched this
        cycle alongside the advanced ``f"{log_type}_last_offset"`` for each
        stream; it is not an accumulator over cycles.

        :param alloc: The allocation details from Nomad.
        :type alloc: dict[str, Any]
        :param initial_logs: Per-step starting offsets in the shape
            ``{step: {f"{log_type}_last_offset": int}}``. Content fields are
            ignored.
        :type initial_logs: dict[str, dict[str, Any]] | None
        :param anonymize_entities: PII entities to anonymize in run-script /
            step1 output. When ``None``, no anonymization is performed.
        :type anonymize_entities: set[PIIEntity] | None
        :return: A dict containing this cycle's delta log content and the new
            last offsets, shaped
            ``{step: {log_type: delta_text, f"{log_type}_last_offset": int}}``.
        :rtype: dict[str, dict[str, Any]]
        """
        alloc_id = alloc["ID"]
        task_logs = defaultdict(dict)
        log_type_values = {log_type.value for log_type in TaskLogType}
        for step, payload in (initial_logs or {}).items():
            for key, value in payload.items():
                if isinstance(key, TaskLogType):
                    continue
                if isinstance(key, str) and key in log_type_values:
                    continue
                task_logs[step][key] = value
        task_states = alloc["TaskStates"] or {}
        for step, log_type in product(task_states, TaskLogType):
            if task_states[step].get("StartedAt") is None:
                continue
            last_offset_key = f"{log_type}_last_offset"
            start_offset = task_logs[step].get(last_offset_key) or 0
            delta, new_offset = self._fetch_step_log_delta(
                alloc_id, step, log_type, start_offset, anonymize_entities
            )
            task_logs[step][last_offset_key] = new_offset
            task_logs[step][log_type] = delta
        return task_logs

    def _resolve_running_allocation(
        self, queue_item: TaskHistory
    ) -> tuple[dict[str, Any], str] | None:
        """Resolve the current allocation for a running task history.

        Walks any ``FollowupEvalID`` chain to land on the latest allocation. If
        the allocation is gone, mutates ``queue_item.status`` to FAILED or LOST
        and returns ``None`` so the caller knows to bail out without further
        work.

        :param queue_item: The running task history record.
        :type queue_item: TaskHistory
        :return: ``(alloc, job_id)`` when an allocation is found, or ``None``
            when the caller should return early.
        :rtype: tuple[dict[str, Any], str] | None
        """
        try:
            alloc = self.get_allocation_for_task_history(queue_item)
            job_id = alloc["JobID"]
            while followup_eval_id := alloc.get("FollowupEvalID"):
                alloc = self.get_last_allocation(job_id, followup_eval_id)
                queue_item.execution_request.tracking["task_states"] = {}
        except AllocationNotFoundError:
            logger.debug("Allocation not found for task history %s", queue_item.id)
        else:
            return alloc, job_id
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
        except JobNotFoundError:
            logger.warning(
                "Lost job and allocation from task history %s", queue_item.id
            )
            queue_item.status = TaskHistoryStatusEnum.LOST
        return None

    async def _sync_task_history(
        self,
        queue_item: TaskHistory,
        writer_session: AsyncSession | None = None,
    ) -> TaskHistory:
        """Synchronize the task history with the current state of the task in Nomad.

        Retrieve the latest allocation, update the status and the execution
        tracking metadata, and persist the delta logs fetched from Nomad into
        ``taskhistory_log`` via :class:`TaskHistoryLogWriter`. Legacy
        ``tracking["task_logs"]`` blobs are migrated into the chunk store on
        the first post-deployment sync via :func:`backfill_legacy_logs`, so
        pre-existing records keep a continuous log stream.

        :param queue_item: The task history record for tracking this execution.
        :type queue_item: TaskHistory
        :param writer_session: The dedicated session to use for log chunk
            persistence. When ``None``, log persistence is skipped.
        :type writer_session: AsyncSession | None
        :return: The updated task history with execution details.
        :rtype: TaskHistory
        """
        if queue_item.status != TaskHistoryStatusEnum.RUNNING:
            return queue_item

        previous_allocation_id = queue_item.execution_request.tracking.get(
            "allocation_id"
        )

        resolved = self._resolve_running_allocation(queue_item)
        if resolved is None:
            return queue_item
        alloc, job_id = resolved

        task_states = alloc["TaskStates"]

        try:
            job = self.get_job(job_id)
        except JobNotFoundError:
            queue_item.status = TaskHistoryStatusEnum.LOST
        else:
            if job["Status"] == NOMAD_DEAD_JOB_STATUS:
                last_modified_timestamp = alloc.get("ModifyTime")
                if last_modified_timestamp:
                    queue_item.finished_at = self.timestamp_to_datetime(
                        last_modified_timestamp
                    )
                else:
                    queue_item.finished_at = utc_now()

                queue_item.status = self.get_task_history_status_from_alloc_status(
                    alloc["ClientStatus"],
                    queue_item.status,
                    stopped=job.get("Stop", False),
                )

        if writer_session is not None:
            await self._persist_nomad_task_logs(
                writer_session=writer_session,
                queue_item=queue_item,
                alloc=alloc,
                previous_allocation_id=previous_allocation_id,
            )

        queue_item.execution_request.tracking.update(
            allocation_id=alloc["ID"],
            job_id=job_id,
            evaluation_id=alloc["EvalID"],
            task_states=task_states,
        )
        queue_item.execution_request.tracking.pop("task_logs", None)
        return queue_item

    async def _persist_nomad_task_logs(
        self,
        *,
        writer_session: AsyncSession,
        queue_item: TaskHistory,
        alloc: dict[str, Any],
        previous_allocation_id: str | None,
    ) -> None:
        """Persist this sync cycle's delta logs into the chunk store.

        Resets the producer offset to ``0`` for every stream when Nomad
        reschedules to a new allocation so the fetcher reads the new
        allocation from the start.

        :param writer_session: The dedicated session used for log chunk
            persistence, supplied by the caller.
        :type writer_session: AsyncSession
        :param queue_item: The running task history record.
        :type queue_item: TaskHistory
        :param alloc: The current Nomad allocation dict.
        :type alloc: dict[str, Any]
        :param previous_allocation_id: The ``allocation_id`` stored in
            ``tracking`` at the start of this sync cycle, or ``None`` when the
            record has not yet landed on an allocation.
        :type previous_allocation_id: str | None
        """
        alloc_id = alloc["ID"]
        legacy_logs = decompress_legacy_logs(queue_item)
        if legacy_logs:
            await backfill_legacy_logs(writer_session, queue_item.id, legacy_logs)

        allocation_switched = (
            previous_allocation_id is not None and previous_allocation_id != alloc_id
        )
        if allocation_switched:
            await TaskHistoryLogStateManager.reset_producer_offsets(
                writer_session, queue_item.id
            )
            await writer_session.commit()
        state_rows = await TaskHistoryLogStateManager.list_for_task(
            writer_session, queue_item.id
        )
        initial_offsets = defaultdict(dict)
        for row in state_rows:
            initial_offsets[row.source][f"{row.stream.value}_last_offset"] = (
                row.producer_offset
            )

        task_logs = self.get_logs_for_allocation(
            alloc,
            initial_offsets,
            queue_item.anonymized_entities,
        )

        force_flush = queue_item.status != TaskHistoryStatusEnum.RUNNING
        for step, payload in task_logs.items():
            for log_type in TaskLogType:
                delta_text = payload.get(log_type) or ""
                if not delta_text and not force_flush:
                    continue
                last_offset = payload.get(f"{log_type.value}_last_offset", 0)
                await TaskHistoryLogWriter.append(
                    writer_session,
                    queue_item.id,
                    source=step,
                    stream=log_type,
                    new_bytes=delta_text.encode("utf-8"),
                    producer_offset_after=last_offset,
                    force_flush=force_flush,
                )

        if force_flush:
            for row in await TaskHistoryLogStateManager.list_for_task(
                writer_session, queue_item.id
            ):
                await TaskHistoryLogWriter.append(
                    writer_session,
                    queue_item.id,
                    source=row.source,
                    stream=row.stream,
                    new_bytes=b"",
                    force_flush=True,
                )

    def task_needs_job_register(self, task: Task) -> bool:
        """Determine whether a job needs to be registered for the task.

        Checks the task's configuration to decide if a job should be registered. If the
        task is a parameterized job, it checks if the job exists and if it has been
        updated since the last submission. For other job types, it currently assumes
        that a new job needs to be created.

        :param task: The task to evaluate.
        :type task: Task
        :return: `True` if a new job needs to be created, otherwise ``False``.
        :rtype: bool
        :raises BaseNomadException: If there is an issue communicating with the Nomad
            backend.
        """
        if task.data.get("ParameterizedJob"):
            try:
                job = self.get_job(task.data["ID"])
            except JobNotFoundError:
                return True
            return (submit_time := job.get("SubmitTime")) is None or make_datetime_utc(
                task.updated_at or task.created_at
            ) > self.timestamp_to_datetime(submit_time)
        return True

    # TODO: Use pydantic models instead of dict for job validation  # noqa: TD002, TD003
    async def validate_job(self, job: dict[str, Any]) -> dict[str, Any]:
        """Validate a Nomad job specification.

        This function sends a job specification to the Nomad backend for validation.
        If validation fails, it raises an HTTPException with the corresponding status code.

        :param job: The Nomad job specification to validate.
        :type job: dict[str, Any]
        :return: The original job specification if validation is successful.
        :rtype: dict[str, Any]
        :raises HTTPBadRequestException: If validation fails or Nomad returns an
            error status code.
        """
        valid = await async_run(self.backend.validate.validate_job, {"Job": job})
        if valid.status_code != status.HTTP_200_OK:
            raise HTTPBadRequestException(
                f"Nomad job validation failed with status {valid.status_code}"
            )
        resp = json.loads(valid.text)
        if not resp.get("ValidationErrors", []):
            return job
        logger.error(valid[0].text)
        raise HTTPBadRequestException("Invalid job specification")

    def _stream_log_timing(
        self,
        stream_start: float | None,
        params: dict[str, Any],
        start_offset: int,
    ) -> tuple[float, Any]:
        """Compute elapsed time and offset for Nomad log stream log messages.

        :param stream_start: Monotonic time when the HTTP body read started, or
            ``None`` if the stream had not reached that phase yet.
        :type stream_start: float | None
        :param params: Query parameters for the log request (may include updated
            ``offset`` from framed chunks).
        :type params: dict[str, Any]
        :param start_offset: Initial offset passed into the stream request.
        :type start_offset: int
        :return: Elapsed seconds since ``stream_start`` (0 if unknown) and the
            offset value to include in logs.
        :rtype: tuple[float, Any]
        """
        elapsed = time.monotonic() - stream_start if stream_start is not None else 0
        offset = params.get("offset", start_offset)
        return elapsed, offset

    def _log_stream_timeout(
        self,
        alloc_id: str,
        step: str,
        log_type: TaskLogType,
        stream_start: float | None,
        params: dict[str, Any],
        start_offset: int,
    ) -> None:
        """Log a socket read timeout while streaming Nomad task logs.

        :param alloc_id: Nomad allocation ID.
        :type alloc_id: str
        :param step: Task step name.
        :type step: str
        :param log_type: Log stream type (stdout/stderr).
        :type log_type: TaskLogType
        :param stream_start: Monotonic time when body read started, or ``None``.
        :type stream_start: float | None
        :param params: Request query parameters.
        :type params: dict[str, Any]
        :param start_offset: Initial stream offset.
        :type start_offset: int
        """
        elapsed, offset = self._stream_log_timing(stream_start, params, start_offset)
        logger.warning(
            "Nomad log stream sock_read timeout alloc_id=%s step=%s log_type=%s "
            "offset=%s elapsed=%.2fs timeout=%ss. "
            "Consider increasing TASKS__NOMAD__LOG_SOCKET_READ_TIMEOUT (current: %s)",
            alloc_id,
            step,
            log_type,
            offset,
            elapsed,
            self.log_socket_read_timeout,
            self.log_socket_read_timeout,
        )

    def _log_stream_cancelled(
        self,
        alloc_id: str,
        step: str,
        log_type: TaskLogType,
        stream_start: float | None,
        params: dict[str, Any],
        start_offset: int,
    ) -> None:
        """Log that a Nomad log stream was cancelled.

        :param alloc_id: Nomad allocation ID.
        :type alloc_id: str
        :param step: Task step name.
        :type step: str
        :param log_type: Log stream type (stdout/stderr).
        :type log_type: TaskLogType
        :param stream_start: Monotonic time when body read started, or ``None``.
        :type stream_start: float | None
        :param params: Request query parameters.
        :type params: dict[str, Any]
        :param start_offset: Initial stream offset.
        :type start_offset: int
        """
        elapsed, offset = self._stream_log_timing(stream_start, params, start_offset)
        logger.info(
            "Nomad log stream cancelled alloc_id=%s step=%s log_type=%s "
            "offset=%s elapsed=%.2fs",
            alloc_id,
            step,
            log_type,
            offset,
            elapsed,
        )

    def _log_stream_client_error(
        self,
        alloc_id: str,
        step: str,
        log_type: TaskLogType,
        stream_start: float | None,
        params: dict[str, Any],
        start_offset: int,
    ) -> None:
        """Log an aiohttp :exc:`~aiohttp.ClientError` while streaming Nomad logs.

        :param alloc_id: Nomad allocation ID.
        :type alloc_id: str
        :param step: Task step name.
        :type step: str
        :param log_type: Log stream type (stdout/stderr).
        :type log_type: TaskLogType
        :param stream_start: Monotonic time when body read started, or ``None``.
        :type stream_start: float | None
        :param params: Request query parameters.
        :type params: dict[str, Any]
        :param start_offset: Initial stream offset.
        :type start_offset: int
        """
        elapsed, offset = self._stream_log_timing(stream_start, params, start_offset)
        logger.exception(
            "Error fetching Nomad logs (ClientError) alloc_id=%s step=%s "
            "log_type=%s offset=%s elapsed=%.2fs",
            alloc_id,
            step,
            log_type,
            offset,
            elapsed,
        )

    async def _push_logs_to_queue(
        self,
        # TODO(yan): Use Pydantic model for alloc
        # SEP-154
        alloc: dict[str, Any],
        step: str,
        log_type: TaskLogType,
        queue: asyncio.Queue,
        start_offset: int = 0,
        anonymize_entities: set[PIIEntity] | None = None,
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
        :param start_offset: The offset to start reading logs from. Defaults to 0.
        :type start_offset: int
        """
        timeout = ClientTimeout(sock_read=self.log_socket_read_timeout)
        params = {
            "task": step,
            "type": log_type,
            "follow": "true",
            "offset": start_offset,
        }
        state = "running"
        while state == "running":
            alloc_id = alloc["ID"]
            stream_start = None
            try:
                state, alloc, stream_start = await self._consume_nomad_log_stream(
                    alloc=alloc,
                    step=step,
                    log_type=log_type,
                    queue=queue,
                    params=params,
                    client_timeout=timeout,
                    anonymize_entities=anonymize_entities,
                )
            except asyncio.CancelledError:
                self._log_stream_cancelled(
                    alloc_id,
                    step,
                    log_type,
                    stream_start,
                    params,
                    start_offset,
                )
                raise

            if state == _NOMAD_LOG_STREAM_SOCK_TIMEOUT:
                self._log_stream_timeout(
                    alloc_id,
                    step,
                    log_type,
                    stream_start,
                    params,
                    start_offset,
                )
                break
            if state == _NOMAD_LOG_STREAM_CLIENT_ERROR:
                self._log_stream_client_error(
                    alloc_id,
                    step,
                    log_type,
                    stream_start,
                    params,
                    start_offset,
                )
                break
        await queue.put(TaskLog(step=step, type=log_type, msg=None))

    async def _consume_nomad_log_stream(
        self,
        alloc: dict[str, Any],
        step: str,
        log_type: TaskLogType,
        queue: asyncio.Queue,
        params: dict[str, Any],
        client_timeout: ClientTimeout,
        anonymize_entities: set[PIIEntity] | None,
    ) -> tuple[str, dict[str, Any], float | None]:
        """Perform a single Nomad log streaming HTTP request and consume chunks.

        Opens ``/v1/client/fs/logs/{alloc_id}``, handles 404 while the task has not
        started, streams framed JSON log lines into ``queue``, and returns when the
        stream ends or the allocation task state should be rechecked.

        On socket read timeout or :exc:`~aiohttp.ClientError`, returns internal state
        constants ``_NOMAD_LOG_STREAM_SOCK_TIMEOUT`` or ``_NOMAD_LOG_STREAM_CLIENT_ERROR``
        so the caller can log and stop without misclassifying cancellations.

        :param alloc: Nomad allocation dictionary (must include ``ID``, ``JobID``,
            ``EvalID``, and ``TaskStates``).
        :type alloc: dict[str, Any]
        :param step: Task step name for the ``task`` query parameter.
        :type step: str
        :param log_type: ``stdout`` or ``stderr``.
        :type log_type: TaskLogType
        :param queue: Queue to push :class:`~app.tasks.models.TaskLog` records into.
        :type queue: asyncio.Queue
        :param params: Mutable request query parameters (``offset`` is updated).
        :type params: dict[str, Any]
        :param client_timeout: aiohttp client timeout (e.g. socket read timeout).
        :type client_timeout: ClientTimeout
        :param anonymize_entities: Optional PII entities to redact for specific steps.
        :type anonymize_entities: set[PIIEntity] | None
        :return: Nomad task ``State`` string, ``running`` to continue the outer
            loop, or a ``_NOMAD_LOG_STREAM_*`` sentinel; the allocation dict (possibly
            refreshed); and monotonic time when response body reads began, or
            ``None`` if that phase was not reached.
        :rtype: tuple[str, dict[str, Any], float | None]
        """
        alloc_id = alloc["ID"]
        stream_start = None
        logger.debug("Requesting logs for %s with params %s", alloc_id, params)
        try:
            async with self._request(
                "GET",
                f"/v1/client/fs/logs/{alloc_id}",
                params=params,
                timeout=client_timeout,
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
                    return ("running", alloc, stream_start)
                response.raise_for_status()
                stream_start = time.monotonic()
                logger.info(
                    "Nomad log stream started alloc_id=%s step=%s log_type=%s "
                    "sock_read_timeout=%ss offset=%s",
                    alloc_id,
                    step,
                    log_type,
                    self.log_socket_read_timeout,
                    params["offset"],
                )
                empty_data_count = 0
                raw_data = b""
                first_chunk_seen = False
                async for chunk, _ in response.content.iter_chunks():
                    raw_data += chunk
                    if b"}" not in chunk:
                        continue
                    data = json.loads(raw_data)
                    raw_data = b""
                    params["offset"] = offset = data.get("Offset", params["offset"])
                    if data and (msg := data.get("Data")):
                        empty_data_count = 0
                        if not first_chunk_seen:
                            first_chunk_seen = True
                            elapsed = (
                                time.monotonic() - stream_start
                                if stream_start is not None
                                else 0
                            )
                            logger.debug(
                                "First log chunk received alloc_id=%s step=%s "
                                "log_type=%s offset=%s elapsed=%.2fs",
                                alloc_id,
                                step,
                                log_type,
                                offset,
                                elapsed,
                            )
                        decoded_msg = b64decode_str(msg)
                        if step in ("run-script", "step1"):
                            decoded_msg = anonymize_text(
                                decoded_msg, anonymize_entities or set()
                            )
                        await queue.put(
                            TaskLog(
                                step=step, type=log_type, msg=decoded_msg, offset=offset
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
                        return (
                            alloc["TaskStates"][step]["State"],
                            alloc,
                            stream_start,
                        )
                    else:
                        empty_data_count += 1
                return ("running", alloc, stream_start)
        except TimeoutError:
            return (_NOMAD_LOG_STREAM_SOCK_TIMEOUT, alloc, stream_start)
        except ClientError:
            return (_NOMAD_LOG_STREAM_CLIENT_ERROR, alloc, stream_start)

    def preflight_stream_logs(self, queue_item: TaskHistory) -> None:
        """Resolve allocation for live log streaming before HTTP response headers are sent."""
        job_id, eval_id = self.job_eval_ids_for_stream_logs(queue_item)
        self.get_last_allocation(job_id, eval_id)

    def job_eval_ids_for_stream_logs(self, queue_item: TaskHistory) -> tuple[str, str]:
        """Return job_id and evaluation_id from task history tracking for log streaming."""
        return (
            queue_item.execution_request.tracking["job_id"],
            queue_item.execution_request.tracking["evaluation_id"],
        )

    async def stream_logs(
        self,
        queue_item: TaskHistory,
        start_offsets: dict[str, dict[str, int]] | None = None,
    ) -> AsyncGenerator[TaskLog | None, None]:
        """Stream logs from a task history record.

        Retrieves the allocation details and concurrently streams stdout and stderr logs
        for each task step. Yields ``TaskLog`` instances as log lines are received.

        :param queue_item: The task history record for tracking the logs.
        :type queue_item: TaskHistory
        :param start_offsets: A dictionary containing the starting offsets for each
            step and log type. If None, defaults to starting from the beginning.
        :type start_offsets: dict[str, dict[str, int]] | None
        :return: An async generator yielding ``TaskLog`` instances containing
            log messages.
        :rtype: AsyncGenerator[TaskLog | None, None]
        """
        job_id, eval_id = self.job_eval_ids_for_stream_logs(queue_item)
        alloc = self.get_last_allocation(job_id, eval_id)
        active_streams = set()
        queue = asyncio.Queue()
        push_logs_tasks = []
        task_states = alloc["TaskStates"]
        if task_states:
            start_offsets = defaultdict(dict, start_offsets or {})
            for step, log_type in product(task_states, TaskLogType):
                stream = (step, log_type)
                logger.debug("Adding %s to active_streams", stream)
                active_streams.add(stream)
                push_logs_tasks.append(
                    asyncio.create_task(
                        self._push_logs_to_queue(
                            alloc,
                            step,
                            log_type,
                            queue,
                            start_offsets[step].get(log_type, 0),
                            queue_item.anonymized_entities,
                        )
                    )
                )
            try:
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
            finally:
                for task in push_logs_tasks:
                    task.cancel()
                await asyncio.gather(*push_logs_tasks, return_exceptions=True)
        else:
            yield None

    async def stream_file(
        self, queue_item: TaskHistory, path: str, chunk_size: int = _ONE_MEBIBYTE
    ) -> AsyncGenerator[bytes, None]:
        """Stream a file from the allocation's filesystem in chunks.

        Directories are archived on the fly and streamed as a tar.gz archive.

        :param queue_item: The task history record for tracking the logs.
        :type queue_item: TaskHistory
        :param path: The path to the file to be streamed.
        :type path: str
        :param chunk_size: The size of each chunk to read from the file. Defaults to
            1 MiB.
        :type chunk_size: int
        :return: An async generator yielding chunks of the file as bytes.
        :rtype: AsyncGenerator[bytes, None]
        """
        alloc = self.get_allocation_for_task_history(queue_item)
        alloc_id = alloc["ID"]
        params = {"path": path}
        async with self._request(
            "GET", f"/v1/client/fs/stat/{alloc_id}", params=params
        ) as response:
            response.raise_for_status()
            stat = await response.json()
        logger.debug("File stat: %r", stat)

        if self._is_directory(stat):
            logger.info("Requested path %s is a directory, streaming as tar.gz", path)
            async for chunk in self._stream_directory_as_tar_gz(
                queue_item, alloc_id, path
            ):
                yield chunk
            return

        file_size = stat.get("Size", 0)
        if file_size == 0:
            logger.warning("File %s is empty or does not exist", path)
            yield b""
            return
        logger.info("Starting to stream file %s of size %s", path, file_size)
        endpoint = f"/v1/client/fs/readat/{alloc_id}"
        params["limit"] = chunk_size
        for offset in range(0, file_size, chunk_size):
            params["offset"] = offset
            async with self._request("GET", endpoint, params=params) as response:
                response.raise_for_status()
                content = await response.read()
                if queue_item.anonymized_entities:
                    try:
                        text = content.decode()
                        yield anonymize_text(
                            text, queue_item.anonymized_entities
                        ).encode()
                        continue
                    except UnicodeDecodeError:
                        logger.debug(
                            "Could not decode file content, sending raw bytes",
                            exc_info=True,
                        )
                yield content

    @staticmethod
    def _is_directory(stat: dict[str, Any]) -> bool:
        """Check whether the given file stat describes a directory."""
        return bool(
            stat.get("IsDir")
            or stat.get("Directory")
            or stat.get("Type") in {"directory", "dir"}
        )

    async def _iter_directory_entries(
        self, alloc_id: str, path: str, relative_prefix: str
    ) -> AsyncGenerator[tuple[str, str, bool, int], None]:
        """Yield directory entries recursively with absolute and relative paths."""
        async with self._request(
            "GET", f"/v1/client/fs/ls/{alloc_id}", params={"path": path}
        ) as response:
            response.raise_for_status()
            entries = await response.json()

        for entry in entries:
            name = entry["Name"]
            if name.startswith("."):
                continue
            is_dir = bool(
                entry.get("IsDir")
                or entry.get("Directory")
                or entry.get("Type") in {"directory", "dir"}
            )
            size = entry.get("Size", 0)
            abs_path = "/".join([path.rstrip("/"), name]).replace("//", "/")
            rel_path = f"{relative_prefix}/{name}".lstrip("/")
            rel_path = (
                f"{rel_path}/" if is_dir and not rel_path.endswith("/") else rel_path
            )
            yield abs_path, rel_path, is_dir, size
            if is_dir:
                async for sub_entry in self._iter_directory_entries(
                    alloc_id, abs_path, rel_path.rstrip("/")
                ):
                    yield sub_entry

    async def _read_file_bytes(
        self,
        queue_item: TaskHistory,
        alloc_id: str,
        path: str,
        file_size: int,
        chunk_size: int = _ONE_MEBIBYTE,
    ) -> bytes:
        """Read a remote file fully, applying anonymization when needed."""
        if file_size == 0:
            return b""
        endpoint = f"/v1/client/fs/readat/{alloc_id}"
        params = {"path": path, "limit": chunk_size}
        content = bytearray()
        for offset in range(0, file_size, chunk_size):
            params["offset"] = offset
            async with self._request("GET", endpoint, params=params) as response:
                response.raise_for_status()
                chunk = await response.read()
                if queue_item.anonymized_entities:
                    try:
                        text = chunk.decode()
                        chunk = anonymize_text(
                            text, queue_item.anonymized_entities
                        ).encode()
                    except UnicodeDecodeError:
                        logger.debug(
                            "Could not decode file content for anonymization, sending raw bytes",
                            exc_info=True,
                        )
                content.extend(chunk)
        if len(content) != file_size:
            logger.warning(
                "Read %s bytes for %s but expected %s; using actual length",
                len(content),
                path,
                file_size,
            )
        return bytes(content)

    async def _stream_directory_as_tar_gz(
        self, queue_item: TaskHistory, alloc_id: str, path: str
    ) -> AsyncGenerator[bytes, None]:
        """Archive a directory on the fly and stream it as a tar.gz archive."""
        queue = asyncio.Queue()
        root_name = Path(path.rstrip("/")).name or "archive"

        class QueueWriter:
            def __init__(self, target_queue: asyncio.Queue[bytes | None]) -> None:
                self.queue = target_queue

            def write(self, data: bytes) -> int:  # pragma: no cover - trivial
                self.queue.put_nowait(data)
                return len(data)

        async def produce() -> None:
            try:
                writer = QueueWriter(queue)
                with tarfile.open(mode="w|gz", fileobj=writer) as tar:
                    root_info = tarfile.TarInfo(name=f"{root_name}/")
                    root_info.type = tarfile.DIRTYPE
                    tar.addfile(root_info)
                    async for (
                        abs_path,
                        rel_path,
                        is_dir,
                        size,
                    ) in self._iter_directory_entries(alloc_id, path, root_name):
                        try:
                            tarinfo = tarfile.TarInfo(name=rel_path)
                            tarinfo.mtime = int(utc_now().timestamp())
                            if is_dir:
                                tarinfo.type = tarfile.DIRTYPE
                                tar.addfile(tarinfo)
                                continue
                            file_bytes = await self._read_file_bytes(
                                queue_item, alloc_id, abs_path, size
                            )
                            tarinfo.size = len(file_bytes)
                            tar.addfile(tarinfo, fileobj=io.BytesIO(file_bytes))
                        except Exception:
                            logger.exception(
                                "Failed to add %s to tarball, skipping entry", rel_path
                            )
                            continue
            finally:
                await queue.put(None)

        producer = asyncio.create_task(produce())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            await producer

    async def list_files(
        self, queue_item: TaskHistory, path: str
    ) -> dict[str, FileMetadata]:
        """List files in a directory on the allocation's filesystem.

        :param queue_item: The task history record for tracking the logs.
        :type queue_item: TaskHistory
        :param path: The path to the directory to list files from.
        :type path: str
        :return: A dictionary with filenames as keys and their metadata as values.
            The metadata includes the file size and whether it is a directory.
        :rtype: dict[str, FileMetadata]
        """
        alloc = self.get_allocation_for_task_history(queue_item)
        alloc_id = alloc["ID"]
        async with self._request(
            "GET", f"/v1/client/fs/ls/{alloc_id}", params={"path": path}
        ) as response:
            response.raise_for_status()
            files = await response.json()
        return {
            filename: FileMetadata(
                size=file.get("Size", 0),
                is_dir=bool(
                    file.get("IsDir")
                    or file.get("Directory")
                    or file.get("Type") in {"directory", "dir"}
                ),
            )
            for file in files
            if not (filename := file["Name"]).startswith(".")
        }

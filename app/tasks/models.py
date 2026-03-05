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

"""Define models for the Task API."""

import base64
import gzip
import json
from collections import defaultdict
from collections.abc import Generator
from datetime import datetime
from enum import auto, StrEnum
from functools import cached_property
from itertools import product
from pathlib import Path
from statistics import mean
from typing import Annotated, Any, Literal, Self

from pydantic import (
    BaseModel,
    BeforeValidator,
    computed_field,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
    ValidationError,
)
from sqlalchemy import Column, Index, JSON
from sqlalchemy import Enum as EnumField
from sqlalchemy.types import TypeDecorator
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.alerts.config import alert_service
from app.core.alerts.models import AlertSeverity
from app.core.db import BaseSQLModel
from app.core.db.models import DateTimeWithTimezone
from app.core.utils.fields import (
    EmptyStrToNone,
    EnumFieldMixin,
    UTCDatetime,
)
from app.tasks.anonymizer.config import anonymizer_settings
from app.tasks.anonymizer.entities import PIIEntity

TASK_ALIAS_LENGTH = 100
SYSTEM_USER = "SYSTEM"


def _encode_anonymize_mask(v: Any) -> Any:
    """Encode the anonymize mask from a set of PII entities.

    If the input is a set of PIIEntity, it encodes it into an integer bitmask.
    Otherwise, it returns it as is.

    :param v: The input value to encode.
    :type v: Any
    :return: The encoded anonymize mask as an integer or the original input in case of
        a TypeError.
    :rtype: Any
    """
    try:
        return PIIEntity.encode_selection(v)
    except TypeError:
        return v


AnonymizeMask = Annotated[int, BeforeValidator(_encode_anonymize_mask)]


class FileMetadata(BaseModel):
    """Represent file metadata for task artifacts."""

    size: int = 0
    is_dir: bool = False

    model_config = ConfigDict(extra="ignore")


class TaskBackendEnum(StrEnum):
    """Control the choice of backends.

    :cvar NOMAD: Enum value for Nomad backend.
    :vartype NOMAD: str
    :cvar PROXY: Enum value for Proxy backend.
    :vartype PROXY: str
    """

    NOMAD = auto()
    PROXY = auto()


class TaskHistoryStatusEnum(StrEnum):
    """Define status codes for task executions.

    :cvar FAILED: Enum value for failed tasks.
    :vartype FAILED: str
    :cvar PENDING: Enum value for pending tasks.
    :vartype PENDING: str
    :cvar RUNNING: Enum value for running tasks.
    :vartype RUNNING: str
    :cvar SUCCESS: Enum value for successfully completed tasks.
    :vartype SUCCESS: str
    :cvar STOPPED: Enum value for stopped tasks.
    :vartype STOPPED: str
    :cvar LOST: Enum value for tasks that are lost.
    :vartype LOST: str
    """

    FAILED = auto()
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()
    STOPPED = auto()
    LOST = auto()

    def is_finished(self) -> bool:
        """Check if the task status indicates that it is finished.

        :return: True if the task status is one of FAILED, SUCCESS, or STOPPED;
            False otherwise.
        :rtype: bool
        """
        return self in [
            TaskHistoryStatusEnum.FAILED,
            TaskHistoryStatusEnum.SUCCESS,
            TaskHistoryStatusEnum.STOPPED,
        ]


class TaskOwner(EnumFieldMixin, StrEnum):
    """Control the choice of task owners.

    :cvar ANY: Value for tasks without owner restrictions.
    :vartype ANY: str
    :cvar ALTERS: Value for schema change tasks.
    :vartype ALTERS: str
    :cvar ARCHIVER: Value for data archiver tasks.
    :vartype ARCHIVER: str
    :cvar BACKUPS: Value for backup tasks.
    :vartype BACKUPS: str
    :cvar RESTORES: Value for restore tasks.
    :vartype RESTORES: str
    :cvar CHECKSUMS: Value for checksum tasks.
    :vartype CHECKSUMS: str
    """

    ANY = "ANY"
    ALTERS = "ALTERS"
    ARCHIVER = "ARCHIVER"
    BACKUPS = "BACKUPS"
    RESTORES = "RESTORES"
    CHECKSUMS = "CHECKSUMS"
    BACKUP_MONGO = "BACKUP_MONGO"
    RESTORE_MONGO = "RESTORE_MONGO"
    BACKUP_PG = "BACKUP_PG"
    MUM = "MUM"


class TaskLogType(StrEnum):
    """Define the type of task log.

    :cvar STDOUT: Enum value for standard output logs.
    :vartype STDOUT: str
    :cvar STDERR: Enum value for standard error logs.
    :vartype STDERR: str
    """

    STDOUT = "stdout"
    STDERR = "stderr"


class TaskLog(BaseModel):
    """Define a task log line.

    :param step: The task step name.
    :type step: str
    :param type: The type of log to stream ('stdout' or 'stderr').
    :type type: TaskLogType
    :param msg: The log message. If None, represents the end of the log for that step.
    :type msg: str | None
    """

    step: str
    type: TaskLogType
    msg: str | None
    offset: int = 0


class TaskExecutionRequest(BaseModel):
    """Represent an execution request.

    :param task: The task name.
    :type task: str
    :param target: The target system or environment.
    :type target: str
    :param meta: Additional metadata for the task. Defaults to an empty dictionary.
    :type meta: dict | None
    :param payload: Optional payload or file path for parameterizing the task.
        Defaults to None.
    :type payload: str | None
    :param tracking: Tracking information for task execution. Defaults to a dictionary
        with keys for allocation and evaluation IDs.
    :type tracking: dict | None
    """

    model_config = ConfigDict(extra="allow")
    task: str
    target: str
    meta: dict | None = {}
    payload: str | None = None
    tracking: dict | None = {"allocation_id": None, "evaluation_id": None}
    eta: datetime | None = None

    @cached_property
    def payload_content(self) -> str | None:
        """Retrieve the content of the payload if it's a file path.

        If the payload starts with "file://", it attempts to read the file content.
        Otherwise, it returns the payload string directly.

        :return: The content of the payload or None if not applicable.
        :rtype: str | None
        """
        if self.payload and self.payload.strip().startswith("file://"):
            payload_path = Path(
                self.payload.strip().replace("file://", "", 1),
            ).resolve()
            if payload_path.is_file():
                with payload_path.open() as payload_file:
                    return payload_file.read()
        return self.payload


class TaskExecutionRequestJSON(TypeDecorator):
    """Define JSON column type that deserializes values into `TaskExecutionRequest`.

    Use this on columns that should store and return `TaskExecutionRequest` objects
    instead of plain dicts. Other JSON columns are unaffected.

    :cvar impl: The underlying SQLAlchemy column type.
    :vartype impl: type[JSON]
    :cvar cache_ok: Whether this type is safe to cache.
    :vartype cache_ok: bool
    """

    impl = JSON
    cache_ok = True

    def process_result_value(self, value: Any, dialect: Any) -> Any:  # noqa: ARG002
        """Deserialize a JSON value into a `TaskExecutionRequest`.

        :param value: The raw value from the database.
        :type value: Any
        :param dialect: The SQLAlchemy dialect in use.
        :type dialect: Any
        :return: A `TaskExecutionRequest` if valid, otherwise the raw value.
        :rtype: Any
        """
        if value is None:
            return value
        try:
            return TaskExecutionRequest(**value)
        except (ValidationError, TypeError):
            return value

    def process_bind_param(self, value: Any, dialect: Any) -> Any:  # noqa: ARG002
        """Serialize a `TaskExecutionRequest` into a dict for storage.

        :param value: The value to store in the database.
        :type value: Any
        :param dialect: The SQLAlchemy dialect in use.
        :type dialect: Any
        :return: A dict representation suitable for JSON storage.
        :rtype: Any
        """
        if value is None:
            return value
        if isinstance(value, TaskExecutionRequest):
            return value.model_dump(mode="json")
        return value


class TaskBase(SQLModel):
    """Define the base structure for task-related operations.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to TaskOwner.ANY.
    :type owner: str
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the task. Defaults to None, meaning the entities
        defined in
        :attr:`app.tasks.anonymizer.config.AnonymizerSettings.DEFAULT_ENTITIES` will be
        used.
    :type anonymize_mask: int | None
    :param alert_on_fail: Whether to trigger an alert on task failure. Defaults to
        False.
    :type alert_on_fail: bool
    """

    name: str = SQLField(min_length=1, max_length=255, unique=True, index=True)
    data: dict = SQLField(sa_column=Column(JSON, nullable=False))
    backend: TaskBackendEnum = SQLField(
        default=TaskBackendEnum.NOMAD,
        sa_column=Column(EnumField(TaskBackendEnum, native_enum=False), nullable=False),
    )
    owner: str = SQLField(
        default=TaskOwner.ANY,
        index=True,
    )
    is_template: bool = SQLField(default=False, index=True)
    protected: bool = False
    alert_on_fail: bool = False
    anonymize_mask: AnonymizeMask | None = None

    @model_validator(mode="after")
    def validate_data_for_backend(self) -> Self:
        """Validate the data for the Proxy backend.

        If the backend is set to `TaskBackendEnum.PROXY`, "task" is a required key in
        the `data` dictionary.

        :return: The validated instance
        :rtype: TaskBase
        :raises ValueError: If the backend is Proxy and "task" is not set in data.
        """
        if self.backend == TaskBackendEnum.PROXY and not self.data.get("task"):
            raise ValueError("data must contain 'task' for Proxy backend")
        return self


class Task(TaskBase, BaseSQLModel, table=True):
    """Represent a task stored in the database.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to TaskOwner.ANY.
    :type owner: TaskOwner
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
    :param alert_on_fail: Whether to trigger an alert on task failure. Defaults to
        False.
    :type alert_on_fail: bool
    :param history: The history of task executions.
    :type history: list[TaskHistory]
    :param deleted_at: The deletion timestamp, if applicable.
    :type deleted_at: UTCDatetime | None
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the task. Defaults to 0 (no anonymization).
    :type anonymize_mask: int | None
    :param created_by: The user ID of the user who created the task.
    :type created_by: str | None
    :param last_updated_by: The user ID of the user who last modified the task.
    :type last_updated_by: str | None
    :param output_files_path: The path where output files generated by the task are
        expected. Only files in this path will be considered for user pulling. Defaults
        to None, meaning no files will be available for pulling.
    :type output_files_path: str | None
    """

    __table_args__ = (
        Index("ix_task_deleted_at_owner", "deleted_at", "owner"),
        Index("ix_task_deleted_at_name", "deleted_at", "name"),
        Index(
            "ix_task_deleted_at_name_is_template",
            "deleted_at",
            "name",
            "is_template",
        ),
    )
    history: list["TaskHistory"] = Relationship(back_populates="task")
    deleted_at: UTCDatetime | None = SQLField(
        sa_type=DateTimeWithTimezone,
        default=None,
        index=True,
    )
    created_by: str | None = None
    last_updated_by: str | None = None
    output_files_path: str | None = None

    @property
    def anonymized_entities(self) -> set[PIIEntity]:
        """Return the set of PII entities to be anonymized.

        :return: A set of PIIEntity to be anonymized.
        :rtype: set[PIIEntity]
        """
        return (
            PIIEntity.decode_selection(self.anonymize_mask)
            if self.anonymize_mask is not None
            else anonymizer_settings.DEFAULT_ENTITIES[self.owner]
        )


class TaskResponse(TaskBase, BaseSQLModel):
    """Represent a task API response.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to TaskOwner.ANY.
    :type owner: TaskOwner
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
    :param alert_on_fail: Whether to trigger an alert on task failure. Defaults to
        False.
    :type alert_on_fail: bool
    :param deleted_at: The deletion timestamp, if applicable.
    :type deleted_at: UTCDatetime | None
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the task. Defaults to 0 (no anonymization).
    :type anonymize_mask: int | None
    :param created_by: The user ID of the user who created the task.
    :type created_by: str | None
    :param last_updated_by: The user ID of the user who last modified the task.
    :type last_updated_by: str | None
    """

    deleted_at: UTCDatetime | None
    created_by: str | None
    last_updated_by: str | None


class TaskWrite(TaskBase):
    """Define the model for creating new tasks.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to TaskOwner.ANY.
    :type owner: TaskOwner
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
    :param alert_on_fail: Whether to trigger an alert on task failure. Defaults to
        False.
    :type alert_on_fail: bool
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the task. Defaults to 0 (no anonymization).
    :type anonymize_mask: int | None
    """


class TaskExecuteRequest(BaseModel):
    """Represent a request to execute a task with additional metadata and payload.

    :param meta: A dictionary of meta variables for the task execution.
        Defaults to an empty dictionary.
    :type meta: dict[str, Any]
    :param payload: Optional payload data or file path for the task execution.
        Defaults to None.
    :type payload: str | None
    :param eta: The earliest time the task can be executed. Defaults to None, meaning
        it will be executed as soon as possible.
    :type eta: datetime | None
    """

    meta: dict[str, Any] = {}
    payload: str | None = None
    eta: datetime | EmptyStrToNone = None
    anonymize_mask: int | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_meta(cls, data: Any) -> Any:
        """Populate the meta field by extracting keys prefixed with 'meta_'.

        This method processes the input data to gather all keys starting with 'meta_'
        and incorporates them into the meta dictionary.

        :param data: The input data containing potential meta fields.
        :type data: Any
        :return: The modified data with the meta field populated.
        :rtype: Any
        """
        if isinstance(data, dict):
            meta = data.get("meta", {})
            for key, value in data.items():
                if key.startswith("meta_"):
                    meta[key.replace("meta_", "")] = value
            data["meta"] = meta
        return data


class TaskHistoryBase(SQLModel):
    """Define the base structure for a TaskHistory.

    :param execution_request: The request that triggered the task execution.
    :type execution_request: TaskExecutionRequest
    :param status: The status of the task execution. Defaults to pending.
    :type status: TaskHistoryStatusEnum
    :param started_at: The datetime when the task execution started.
    :type started_at: UTCDatetime | None
    :param finished_at: The datetime when the task execution finished.
    :type finished_at: UTCDatetime | None
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the execution. Defaults to None, meaning it uses
        the value defined in the associated task's :attr:`Task.anonymize_mask`.
    :type anonymize_mask: int | None
    :param executed_by: The user ID of the user who executed the task.
    :type executed_by: str | None
    """

    execution_request: TaskExecutionRequest = SQLField(
        sa_column=Column(TaskExecutionRequestJSON, nullable=False),
    )
    status: TaskHistoryStatusEnum = SQLField(
        default=TaskHistoryStatusEnum.PENDING,
        sa_column=Column(
            EnumField(TaskHistoryStatusEnum, native_enum=False),
            nullable=False,
            index=True,
        ),
    )
    started_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    finished_at: UTCDatetime | None = SQLField(
        default=None, sa_type=DateTimeWithTimezone
    )
    anonymize_mask: AnonymizeMask | None = None
    executed_by: str | None = None

    @computed_field
    @property
    def duration(self) -> float | None:
        """Return the duration of the task execution in seconds.

        :return: The duration in seconds, or None if not available.
        :rtype: float | None
        """
        if self.started_at and self.finished_at:
            return (self.finished_at - self.started_at).total_seconds()
        return None


class TaskHistory(TaskHistoryBase, BaseSQLModel, table=True):
    """Represent a task execution history.

    :param execution_request: The request that triggered the task execution.
    :type execution_request: TaskExecutionRequest
    :param status: The status of the task execution. Defaults to pending.
    :type status: TaskHistoryStatusEnum
    :param started_at: The datetime when the task execution started.
    :type started_at: UTCDatetime | None
    :param finished_at: The datetime when the task execution finished.
    :type finished_at: UTCDatetime | None
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the execution. Defaults to None, meaning it uses
        the value defined in the associated task's :attr:`Task.anonymize_mask`.
    :type anonymize_mask: int | None
    :param task_id: The ID of the task associated with the execution.
    :type task_id: int
    :param task: The task associated with this execution history.
    :type task: Task
    :param sync_in_progress_started_at: Timestamp lock for a sync currently in progress.
    :type sync_in_progress_started_at: UTCDatetime | None
    :param executed_by: The user ID of the user who executed the task.
    :type executed_by: str | None
    """

    __table_args__ = (
        Index("ix_taskhistory_task_id_status", "task_id", "status"),
        Index(
            "ix_taskhistory_status_sync_in_progress_started_at",
            "status",
            "sync_in_progress_started_at",
        ),
    )
    task_id: int = SQLField(foreign_key="task.id", index=True)
    task: Task = Relationship(back_populates="history")
    sync_in_progress_started_at: UTCDatetime | None = SQLField(
        default=None,
        sa_type=DateTimeWithTimezone,
    )

    @property
    def is_running(self) -> bool:
        """Check if the task is currently running.

        :return: True if the task status is RUNNING, False otherwise.
        :rtype: bool
        """
        return self.status == TaskHistoryStatusEnum.RUNNING

    @property
    def anonymized_entities(self) -> set[PIIEntity]:
        """Return the set of anonymized PII entities.

        :return: A set of anonymized PIIEntity.
        :rtype: set[PIIEntity]
        """
        return PIIEntity.decode_selection(self.anonymize_mask)

    async def alert_for_status(self) -> None:
        """Trigger an alert for failing statuses."""
        if self.status == TaskHistoryStatusEnum.FAILED:
            summary_action = "failed"
            severity = AlertSeverity.ERROR
            alert_class = "task_failure"
        elif self.status == TaskHistoryStatusEnum.LOST:
            summary_action = "execution tracking lost"
            severity = AlertSeverity.WARNING
            alert_class = "task_lost"
        else:
            return

        alert_data = {
            "summary": f"Task {self.execution_request.task!r} ({self.id}) {summary_action} on node {self.execution_request.target!r}.",
            "source": f"{self.execution_request.task}:{self.id}:{self.execution_request.target}",
            "severity": severity,
            "class": alert_class,
        }
        await alert_service.trigger(alert_data)

    @cached_property
    def task_logs(self) -> dict:
        """Return task logs."""
        # TODO(yan): Refactor logs
        # SEP-564
        logs = self.execution_request.tracking.get("task_logs", {})
        if isinstance(logs, str):
            return json.loads(gzip.decompress(base64.b64decode(logs)))
        return logs

    def iter_logs(
        self,
        start_offsets: dict[str, dict[str, int]] | None = None,
        chunk_size: int = 65536,
        step: str | None = None,
    ) -> Generator[TaskLog]:
        """Yield task logs in chunks based on provided start offsets.

        :param start_offsets: A dictionary containing the starting offsets for each
            step and log type. If None, defaults to starting from the beginning.
        :type start_offsets: dict[str, dict[str, int]] | None
        :param chunk_size: The size of each log chunk to yield. Defaults to 65536 bytes.
        :type chunk_size: int
        :param step: If provided, only logs for this specific step will be yielded.
            Defaults to None.
        :type step: str | None
        :yield: TaskLog objects containing log chunks.
        :rtype: Generator[TaskLog]
        """
        task_logs = self.task_logs
        if step is not None:
            task_logs = {step: task_logs.get(step, {})}
        start_offsets = defaultdict(dict, start_offsets or {})
        for (cur_step, log), log_type in product(task_logs.items(), TaskLogType):
            msg = log.get(log_type) or ""
            for chunk_start in range(
                start_offsets[cur_step].get(log_type, 0), len(msg), chunk_size
            ):
                chunk_end = chunk_start + chunk_size
                yield TaskLog(
                    step=cur_step,
                    type=log_type,
                    msg=msg[chunk_start:chunk_end],
                    offset=chunk_end,
                )


class TaskHistoryResponse(TaskHistoryBase, BaseSQLModel):
    """Represent a task history API response.

    :param execution_request: The request that triggered the task execution.
    :type execution_request: TaskExecutionRequest
    :param status: The status of the task execution.
    :type status: TaskHistoryStatusEnum
    :param started_at: The datetime when the task execution started.
    :type started_at: UTCDatetime | None
    :param finished_at: The datetime when the task execution finished.
    :type finished_at: UTCDatetime | None
    :param anonymize_mask: The bitmask representing PII entities to be anonymized in
        logs and files generated by the execution. Defaults to None, meaning it uses
        the value defined in the associated task's :attr:`Task.anonymize_mask`.
    :type anonymize_mask: int | None
    :param task: The task associated with this execution history.
    :type task: TaskResponse
    :param executed_by: The user ID of the user who executed the task.
    :type executed_by: str | None
    """

    task: TaskResponse

    @field_validator("execution_request", mode="after")
    @classmethod
    def _remove_logs(cls, v: TaskExecutionRequest) -> TaskExecutionRequest:
        """Remove logs from the execution request tracking data.

        This validator ensures that any log data present in the tracking information
        of the execution request is removed before returning the response.

        :param v: The TaskExecutionRequest instance to validate.
        :type v: TaskExecutionRequest
        :return: The validated TaskExecutionRequest with logs removed.
        :rtype: TaskExecutionRequest
        """
        # TODO(yan): Refactor logs
        # SEP-564
        v.tracking["task_logs"] = bool(v.tracking.get("task_logs"))
        return v


class TaskStats(BaseModel):
    """Model for task statistics.

    :param engine: The backend engine used for task execution. Defaults to "nomad".
    :type engine: str
    :param tasks: A list of task execution histories.
    :type tasks: list[TaskHistory]
    """

    engine: str = "nomad"
    tasks: list[TaskHistory] = Field(default=[], exclude=True)

    _durations: dict = {
        "average_seconds": None,
        "last_seconds": None,
        "total_seconds": None,
        "tasks": {},
    }
    _raw: dict = {
        "durations": [],
        "finished_at": [],
    }

    @computed_field
    @property
    def total(self) -> int:
        """Return the total number of tasks.

        :return: The total number of tasks.
        :rtype: int
        """
        return len(self.tasks)

    @computed_field
    @property
    def status(self) -> dict:
        """Return the task status summary.

        :return: A dictionary summarizing the number of passed and failed tasks.
        :rtype: dict[str, int]
        """
        status = {
            "pass": 0,
            "fail": 0,
        }
        for task in self.tasks:
            match task.status:
                case TaskHistoryStatusEnum.FAILED:
                    status["fail"] += 1
                case TaskHistoryStatusEnum.SUCCESS:
                    status["pass"] += 1
                case _:
                    pass
        return status

    @computed_field
    @property
    def duration(self) -> dict:
        """Return the task duration summary.

        :return: A dictionary summarizing average, last, and total task durations.
        :rtype: dict[str, Any]
        """
        if self._durations["average_seconds"] is None:
            self._process()
        return self._durations

    @computed_field
    @property
    def last_finished_at(self) -> str | None:
        """Return the last finished task timestamp.

        :return: The timestamp of the last task finished, or None if not available.
        :rtype: str | None
        """
        if not self._raw["finished_at"]:
            self._process()
        return max(self._raw["finished_at"]) if self._raw["finished_at"] else None

    def _process(self) -> None:
        """Process the task data."""

        def _durations_from_tracking() -> None:
            if task.duration is not None:
                self._durations["tasks"][task.id] = task.duration
                self._raw["durations"].append(task.duration)
            if task.finished_at is not None:
                self._raw["finished_at"].append(
                    task.finished_at,
                )

        # TODO:  # noqa: TD002, TD003
        #  - Refactor
        #  - handle extra backends
        #  - consider moving some logic to the TaskHistory model and then call from here
        for i, task in enumerate(self.tasks):
            if i == 0:
                self.engine = task.task.backend
            try:
                _durations_from_tracking()
            except KeyError:
                return
        if self._raw["durations"]:
            self._durations.update(
                average_seconds=mean(self._raw["durations"]),
                last_seconds=self._raw["durations"].pop(),
                total_seconds=sum(self._raw["durations"]),
            )


class TransformPayloadRequest(BaseModel):
    """Define the request body for the /transform/ API route.

    :param payload: The job specification payload to be parsed.
    :type payload: str | bytes
    :param fmt: The format of the payload, which can be "hcl", "json", or "yaml".
    :type fmt: Literal["hcl", "json", "yaml"]
    """

    payload: str | bytes
    fmt: Literal["hcl", "json", "yaml"]


class DispatchLock(BaseSQLModel, table=True):
    """Define a task dispatch lock.

    :param name: The name of the lock. Must be unique.
    :type name: str
    """

    name: str = SQLField(max_length=255, index=True, unique=True)

class NomadVariable(BaseModel):
    """Define the request body for the /transform/ API route.

    :param path: Path of the nomad variable.
    :type path: str | bytes
    :param value: Variable value.
    :type value: str | bytes
    """
    path: str | bytes
    value: str | bytes

class NomadVariableRequest:
    """
    Define a request of a new Nomad variable being created
    :param nomad_variable: Represents a Nomad Variable
    :type nomad_variable: NomadVariable
    """

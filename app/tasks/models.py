# Copyright (C) 2025 Percona LLC
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

from datetime import datetime
from enum import auto, StrEnum
from functools import cached_property
from pathlib import Path
from statistics import mean
from typing import Any, Literal, Self

from pydantic import (
    AliasGenerator,
    BaseModel,
    computed_field,
    ConfigDict,
    Field,
    model_validator,
)
from sqlalchemy import Column, Index, JSON
from sqlalchemy import Enum as EnumField
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

TASK_ALIAS_LENGTH = 100


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

    ANY = "*"
    ALTERS = auto()
    ARCHIVER = auto()
    BACKUPS = auto()
    RESTORES = auto()
    CHECKSUMS = auto()
    BACKUP_MONGO = auto()


class TaskOutput(BaseModel):
    """Represents stdout and stderr for a given task execution.

    :param stdout: A list of dictionaries representing standard output logs.
    :type stdout: list[dict]
    :param stderr: A list of dictionaries representing standard error logs.
    :type stderr: list[dict]
    """

    stdout: list[dict] | None
    stderr: list[dict] | None


class TaskExecutionResult(BaseModel):
    """Represents the overall execution result with different task outputs.

    :param prepare_env: The output of the 'prepare-env' task.
    :type prepare_env: TaskOutput
    :param clean_up: The output of the 'clean-up' task.
    :type clean_up: TaskOutput
    :param run_script: The output of the 'run-script' task.
    :type run_script: TaskOutput
    :param step1: The output of the alters task.
    :type step1: TaskOutput
    """

    prepare_env: TaskOutput | None = Field(alias="prepare-env")
    clean_up: TaskOutput | None = Field(alias="clean-up")
    run_script: TaskOutput | None = Field(alias="run-script")
    step: TaskOutput | None = Field(alias="step1")

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


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


class TaskGroupTaskTemplate(BaseModel):
    """Represent a task group for controlling task templates.

    :param content: The content of the task template.
    :type content: str | bytes
    :param path: The file path where the template will be applied.
    :type path: str
    :param mode: The execution mode of the task. Defaults to "restart".
    :type mode: str
    :param perms: The file permissions for the template. Defaults to "0644".
    :type perms: str
    """

    content: str | bytes
    path: str
    mode: str = "restart"
    perms: str = "0644"

    _transform_fields = {
        "nomad": {
            "content": "EmbeddedTmpl",
            "mode": "ChangeMode",
            "path": "DestPath",
            "perms": "Perms",
        },
    }


class TaskGroupTask(BaseModel):
    """Represent a task that belongs to a job task group.

    :param name: The name of the task.
    :type name: str
    :param driver: The driver to be used for task execution. Defaults to "raw_exec".
    :type driver: str
    :param user: The user who will execute the task. Defaults to an empty string.
    :type user: str
    :param config: The configuration details for the task.
    :type config: dict | list | str | bytes
    :param meta: Additional metadata for the task. Defaults to an empty dictionary.
    :type meta: dict
    :param restart: Task restart policy. Defaults to a dictionary specifying no retries.
    :type restart: dict
    :param templates: A list of task templates to be applied. Defaults to an empty list.
    :type templates: list[TaskGroupTaskTemplate]
    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            serialization_alias=lambda field_name: field_name.title(),
        ),
    )  # TODO: Reuse  # noqa: TD002, TD003
    name: str
    driver: str = "raw_exec"
    user: str = ""
    config: dict | list | str | bytes
    meta: dict = {}  # TODO  # noqa: TD002, TD003, TD004
    restart: dict = {"attempts": 0, "mode": "fail"}  # TODO  # noqa: TD002, TD003, TD004
    templates: list[TaskGroupTaskTemplate] = []  # TODO  # noqa: TD002, TD003, TD004


class TaskGroup(BaseModel):
    """Represent a task group.

    :param engine: The backend engine for task execution. Defaults to "nomad".
    :type engine: str
    :param name: The name of the task group. Defaults to "execution".
    :type name: str
    :param parallel: Whether tasks should be executed in parallel. Defaults to False.
    :type parallel: bool
    :param tasks: A list of tasks in the group.
    :type tasks: list[TaskGroupTask]
    """

    engine: str = "nomad"
    name: str = "execution"
    parallel: bool = False
    tasks: list[TaskGroupTask] = []

    # TODO: Return Pydantic model  # noqa: TD002, TD003
    def to_payload(self) -> dict[str, list[dict]]:
        """Convert to a backend-specific payload format.

        :return: A dictionary representing the payload for the task group.
        :rtype: dict[str, list[dict[str, Any]]]
        """
        data = {"TaskGroups": []}
        match self.engine:
            case _:  # Nomad by default and parallelisation is controlled here for now
                if self.parallel:
                    for i, task in enumerate(self.tasks):
                        data["TaskGroups"].append(
                            {
                                "Name": f"{self.name}{i + 1}",
                                "RestartPolicy": {"Attempts": 0},
                                "ReschedulePolicy": {"Attempts": 0},
                                "Tasks": [task.model_dump(by_alias=True)],
                            },
                        )
                else:
                    data["TaskGroups"].append(
                        {
                            "Name": self.name,
                            "RestartPolicy": {"Attempts": 0},
                            "ReschedulePolicy": {"Attempts": 0},
                            "Tasks": [
                                task.model_dump(by_alias=True) for task in self.tasks
                            ],
                        },
                    )
        return data


class GeneratedTask(BaseModel):
    """Represent a generated task.

    :param app: The application name associated with the task.
    :type app: TaskOwner
    :param commands: A list of commands to execute the task.
    :type commands: list[dict[str, Any]]
    :param name: The task name.
    :type name: str
    :param target: The target system for task execution.
    :type target: str
    :param artifacts: Artifacts produced by the task. Defaults to None.
    :type artifacts: list | None
    :param parallel: Whether the task will run in parallel. Defaults to False.
    :type parallel: bool
    :param persist: Whether the task should persist after completion. Defaults to True.
    :type persist: bool
    :param schedule: The scheduling configuration for the task. Defaults to
        {"save_only": True}.
    :type schedule: dict
    :param template: The task template type. Defaults to "batch".
    :type template: str
    :param alert_on_fail: Whether to trigger an alert on task failure. Defaults to
        False.
    :type alert_on_fail: bool
    """

    app: TaskOwner
    commands: list[dict[str, Any]]
    name: str
    target: str
    artifacts: list | None = None
    parallel: bool = False
    persist: bool = True
    schedule: dict = {"save_only": True}
    template: str = "batch"
    alert_on_fail: bool = False


class TaskBase(SQLModel):
    """Define the base structure for task-related operations.

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
    :param anonymize: The bitmask for entities to be anonymized in logs.
    :type anonymize: int
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
    owner: TaskOwner = SQLField(
        default=TaskOwner.ANY,
        sa_column=Column(
            EnumField(TaskOwner, native_enum=False), nullable=False, index=True
        ),
    )
    is_template: bool = SQLField(default=False, index=True)
    protected: bool = False
    alert_on_fail: bool = False

    anonymize: int = SQLField(default=0, nullable=False)

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
    :param anonymize: The bitmask for entities to be anonymized in logs.
    :type anonymize: int
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
    """

    deleted_at: UTCDatetime | None


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
    """

    execution_request: TaskExecutionRequest = SQLField(
        sa_column=Column(JSON, nullable=False),
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
    :param task_id: The ID of the task associated with the execution.
    :type task_id: int
    :param task: The task associated with this execution history.
    :type task: Task
    :param sync_in_progress_started_at: Timestamp lock for a sync currently in progress.
    :type sync_in_progress_started_at: UTCDatetime | None
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
    :param task: The task associated with this execution history.
    :type task: TaskResponse
    """

    task: TaskResponse


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


class DispatchLock(BaseSQLModel, table=True):
    """Define a task dispatch lock.

    :param name: The name of the lock. Must be unique.
    :type name: str
    """

    name: str = SQLField(max_length=255, index=True, unique=True)

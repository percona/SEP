"""Define models for the Task API."""

import json
from datetime import datetime
from enum import auto, StrEnum
from functools import cached_property
from pathlib import Path
from statistics import mean
from typing import Any, Literal, Self
from zoneinfo import available_timezones

from pydantic import (
    AliasGenerator,
    BaseModel,
    computed_field,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy import Column, Index, JSON
from sqlalchemy import Enum as EnumField
from sqlalchemy_celery_beat.models import CrontabSchedule as BaseCrontabSchedule
from sqlalchemy_celery_beat.models import Period, PeriodicTask
from sqlmodel import Field as SQLField
from sqlmodel import Relationship, SQLModel

from app.core.db import BaseSQLModel
from app.core.db.models import DateTimeWithTimezone
from app.core.utils.fields import EmptyStrToNone

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
    """

    FAILED = auto()
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()


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
                                "Name": f"{self.name}{i+1}",
                                "Tasks": [task.model_dump(by_alias=True)],
                            },
                        )
                else:
                    data["TaskGroups"].append(
                        {
                            "Name": self.name,
                            "Tasks": [
                                task.model_dump(by_alias=True) for task in self.tasks
                            ],
                        },
                    )
        return data


class GeneratedTask(BaseModel):
    """Represent a generated task.

    :param app: The application name associated with the task.
    :type app: str
    :param commands: A list of commands to execute the task.
    :type commands: list
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
    """

    app: str
    commands: list
    name: str
    target: str
    artifacts: list | None = None
    parallel: bool = False
    persist: bool = True
    schedule: dict = {"save_only": True}
    template: str = "batch"


class TaskBase(SQLModel):
    """Define the base structure for task-related operations.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to None.
    :type owner: str | None
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
    """

    name: str = SQLField(max_length=255, unique=True, index=True)
    data: dict = SQLField(sa_column=Column(JSON, nullable=False))
    backend: TaskBackendEnum = SQLField(
        default=TaskBackendEnum.NOMAD,
        sa_column=Column(EnumField(TaskBackendEnum, native_enum=False), nullable=False),
    )
    owner: str | None = SQLField(default=None, index=True)
    is_template: bool = SQLField(default=False, index=True)
    protected: bool = False

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

    @field_validator("owner")
    @classmethod
    def validate_owner(cls, v: str | None) -> str | None:
        """Validate the owner field.

        If the owner is set to "*", it is considered as no specific owner and returns
        None.

        :param v: The owner value to validate.
        :type v: str | None
        :return: The validated owner value.
        :rtype: str | None
        """
        if v == "*":
            return None
        return v


class Task(TaskBase, BaseSQLModel, table=True):
    """Represent a task stored in the database.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to None.
    :type owner: str | None
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
    :param history: The history of task executions.
    :type history: list[TaskHistory]
    :param deleted_at: The deletion timestamp, if applicable.
    :type deleted_at: datetime | None
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
    deleted_at: datetime | None = SQLField(
        sa_type=DateTimeWithTimezone,
        default=None,
        index=True,
    )


class TaskWrite(TaskBase):
    """Define the model for creating new tasks.

    :param name: The name of the task.
    :type name: str
    :param data: The task data stored in JSON format.
    :type data: dict
    :param backend: The backend used for task execution. Defaults to Nomad.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task. Defaults to None.
    :type owner: str | None
    :param is_template: Whether the task is a template. Defaults to False.
    :type is_template: bool
    :param protected: Whether the task is protected from deletion. Defaults to False.
    :type protected: bool
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


class IntervalSchedule(BaseModel):
    """Represent an interval schedule.

    :param every: The number of periods between each execution.
    :type every: int
    :param period: The period unit for the interval (e.g., seconds, minutes).
    :type period: Period
    """

    every: int
    period: Period

    def __str__(self) -> str:
        """Return a string representation of the interval schedule.

        Formats the schedule as "every {every} {period}", handling singular forms
        appropriately.

        :return: A formatted string representing the interval schedule.
        :rtype: str
        """
        str_schedule = f"every {self.every} {self.period.value}"
        if self.every == 1:
            return str_schedule[:-1]
        return str_schedule


class CrontabSchedule(BaseModel):
    """Representing a crontab schedule.

    :param minute: Represents the minute component in cron format. Defaults to `"*"`.
    :type minute: str
    :param hour: Represents the hour component in cron format. Defaults to `"*"`.
    :type hour: str
    :param day_of_week: Represents the day of the week component in cron format.
        Defaults to `"*"`.
    :type day_of_week: str
    :param day_of_month: Represents the day of the month component in cron format.
        Defaults to `"*"`.
    :type day_of_month: str
    :param month_of_year: Represents the month component in cron format.
        Defaults to `"*"`.
    :type month_of_year: str
    :param timezone: The timezone for the cron schedule. Defaults to "UTC". Must be a
        valid timezone as returned in `available_timezones()`
    :type timezone: str
    """

    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"
    timezone: str = "UTC"

    def __str__(self) -> str:
        """Return a string representation of the crontab schedule.

        Formats the schedule according to cron expression standards and includes the
        timezone.

        :return: A formatted string representing the crontab schedule.
        :rtype: str
        """
        fmt_kwargs = {
            field: BaseCrontabSchedule.cronexp(value)
            for field, value in self.model_dump(exclude={"timezone"}).items()
        }
        fmt_kwargs["timezone"] = self.timezone or "UTC"
        return (
            "{minute} {hour} {day_of_month} {month_of_year} {day_of_week} "
            "({timezone})"
        ).format(**fmt_kwargs)

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, v: str) -> str:
        """Validate the timezone field.

        Ensures that the provided timezone is among the available timezones.

        :param v: The timezone string to validate.
        :type v: str
        :return: The validated timezone string.
        :rtype: str
        :raises ValueError: If the timezone is not valid.
        """
        if v not in available_timezones():
            raise ValueError(f"{v} is not a valid timezone")
        return v


class BasePeriodicTask(BaseModel):
    """Define the base model for periodic tasks.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The task identifier.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: datetime | None
    :param expires: The expiration time for the task execution.
    :type expires: datetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: TaskExecutionRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    """

    name: str
    task: str
    start_time: datetime | None
    expires: datetime | None
    enabled: bool
    description: str
    execute_request: TaskExecuteRequest | None = None
    interval: IntervalSchedule | None = None
    crontab: CrontabSchedule | None = None

    @model_validator(mode="after")
    def validate_one_schedule_is_set(self) -> Self:
        """Ensure that exactly one scheduling method is set.

        Validates that either `interval` or `crontab` is set, but not both.

        :return: The validated BasePeriodicTask instance.
        :rtype: Self
        :raises ValueError: If both or neither scheduling methods are set.
        """
        if self.interval is None and self.crontab is None:
            raise ValueError("Either `interval` or `crontab` must be set.")
        if self.interval is not None and self.crontab is not None:
            raise ValueError("Only one of `interval` or `crontab` can be set.")
        return self


class PeriodicTaskResponse(BasePeriodicTask):
    """Representing a response for a periodic task API call.

    This model extends `BasePeriodicTask` and includes additional fields such as ID,
    last run time, total run count, and date changed.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The Celery task name.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: datetime | None
    :param expires: The expiration time for the task execution.
    :type expires: datetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: TaskExecutionRequest | None
    :param id: The unique identifier of the periodic task.
    :type id: int
    :param last_run_at: The datetime of the last run.
    :type last_run_at: datetime | None
    :param total_run_count: The total number of times the task has run.
    :type total_run_count: int
    :param date_changed: The datetime when the task was last changed.
    :type date_changed: datetime | None
    :param interval: The interval schedule for the task. Defaults to None. This field
        is populated with the alias "model_intervalschedule".
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None. This field
        is populated with the alias "model_crontabschedule".
    :type crontab: CrontabSchedule | None
    """

    id: int
    last_run_at: datetime | None
    total_run_count: int = 0
    date_changed: datetime | None
    interval: IntervalSchedule | None = Field(
        None, validation_alias="model_intervalschedule"
    )
    crontab: CrontabSchedule | None = Field(
        None, validation_alias="model_crontabschedule"
    )

    @computed_field
    @property
    def period(self) -> str:
        """Get the period string for the periodic task.

        Returns a string representation of the task's schedule based on whether it uses
        an interval or crontab schedule.

        :return: A string representing the task's period.
        :rtype: str
        """
        if self.interval is not None:
            return str(self.interval)
        return str(self.crontab)

    @model_validator(mode="before")
    @classmethod
    def populate_task_data(cls, data: Any) -> Any:
        """Populate task data from a PeriodicTask instance or dictionary.

        Extracts task execution details from the provided data, which can be a
        `PeriodicTask` instance or a dictionary, and sets the `task` and
        `execute_request` fields.

        :param data: The input data containing task execution details.
        :type data: Any
        :return: The modified data with populated task fields.
        :rtype: Any
        """
        if isinstance(data, PeriodicTask):
            data = data.__dict__
        if isinstance(data, dict):
            data["task"] = None
            data["execute_request"] = None
            if (raw_args := data.get("args")) and (args := json.loads(raw_args)):
                data["task"] = args[0]
                if len(args) > 1:
                    data["execute_request"] = args[1]
            if (raw_kwargs := data.get("kwargs")) and (
                kwargs := json.loads(raw_kwargs)
            ):
                data["task"] = kwargs.get("task_name", data["task"])
                data["execute_request"] = kwargs.get(
                    "execution_data", data["execute_request"]
                )
        return data


class PeriodicTaskWrite(BasePeriodicTask):
    """Define the model for writing periodic tasks.

    This model extends `BasePeriodicTask` and includes additional fields required for
    creating or updating periodic tasks in the database.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The SEP task name.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: datetime | None
    :param expires: The expiration time for the task execution.
    :type expires: datetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: TaskExecutionRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    :param kwargs: A JSON string representing additional keyword arguments for the task.
    :type kwargs: str
    """

    kwargs: str

    @model_validator(mode="before")
    @classmethod
    def populate_celery_task_data(cls, data: Any) -> Any:
        """Populate Celery task data before validation.

        Transforms the input data to include the Celery task name and execution data.

        :param data: The input data containing task details.
        :type data: Any
        :return: The modified data with Celery task information.
        :rtype: Any
        """
        if isinstance(data, dict):
            kwargs = {
                "task_name": data.get("task"),
                "execution_data": data.get("execute_request"),
            }
            data["task"] = "app.tasks.celery.execute_task_by_name"
            data["kwargs"] = kwargs
        return data

    @field_validator("kwargs", mode="before")
    @classmethod
    def encode_kwargs(cls, v: Any) -> Any:
        """Encode the kwargs field to a JSON string.

        Converts the `kwargs` dictionary to a JSON string if it is a dictionary.

        :param v: The kwargs value to encode.
        :type v: Any
        :return: The encoded kwargs as a JSON string.
        :rtype: Any
        """
        if isinstance(v, dict):
            return json.dumps(v)
        return v


class PeriodicTaskUpdate(PeriodicTaskWrite):
    """Define the model for updating periodic tasks.

    Extends `PeriodicTaskWrite` and adds validations specific to updating tasks.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The SEP task name.
    :type task: str
    :param start_time: The start time for the task execution.
    :type start_time: datetime | None
    :param expires: The expiration time for the task execution.
    :type expires: datetime | None
    :param enabled: Whether the task is enabled.
    :type enabled: bool
    :param description: A description of the task.
    :type description: str
    :param execute_request: The execution request details for the task.
    :type execute_request: TaskExecutionRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    :param kwargs: A JSON string representing additional keyword arguments for the task.
    :type kwargs: str
    """

    @field_validator("kwargs", mode="before")
    @classmethod
    def encode_kwargs(cls, v: Any) -> Any:
        """Encode the kwargs field and ensure required fields are present.

        Converts the `kwargs` dictionary to a JSON string and validates the presence
        of the 'task_name' field.

        :param v: The kwargs value to encode.
        :type v: Any
        :return: The encoded kwargs as a JSON string.
        :rtype: Any
        :raises ValueError: If 'task_name' is missing in kwargs.
        """
        if isinstance(v, dict):
            if v.get("task_name") is None:
                raise ValueError("Missing required field 'task_name'")
            return json.dumps(v)
        return v


class PeriodicTaskCreate(PeriodicTaskWrite):
    """Define the model for creating periodic tasks.

    Extends `PeriodicTaskWrite` and includes additional fields required for creating
    new periodic tasks.

    :param name: The name of the periodic task.
    :type name: str
    :param task: The SEP task name.
    :type task: str
    :param execute_request: The execution request details for the task.
    :type execute_request: TaskExecutionRequest | None
    :param interval: The interval schedule for the task. Defaults to None.
    :type interval: IntervalSchedule | None
    :param crontab: The crontab schedule for the task. Defaults to None.
    :type crontab: CrontabSchedule | None
    :param kwargs: A JSON string representing additional keyword arguments for the task.
    :type kwargs: str
    :param start_time: The start time for the task execution. Defaults to None.
    :type start_time: datetime | None
    :param expires: The expiration time for the task execution. Defaults to None.
    :type expires: datetime | None
    :param enabled: Whether the task is enabled. Defaults to True.
    :type enabled: bool
    :param description: A description of the task. Defaults to an empty string.
    :type description: str
    """

    start_time: datetime | None = None
    expires: datetime | None = None
    enabled: bool = True
    description: str = ""


class TaskScheduleRequest(TaskExecuteRequest):
    """Represent a request to schedule a task with execution metadata and scheduling details.

    Inherits from `TaskExecuteRequest` and adds scheduling capabilities.

    :param meta: A dictionary of meta variables for the task execution.
        Defaults to an empty dictionary.
    :type meta: dict[str, Any]
    :param payload: Optional payload data or file path for the task execution.
        Defaults to None.
    :type payload: str | None
    :param period: A cron expression representing the schedule for task execution.
        This specifies the timing of the task, determining when it should run based
        on the specified cron format (minute, hour, day of month, month, day of week).
        Defaults to None, meaning the task will not be scheduled.
    :type period: str | None
        :param minute: Represents the minute component in cron format.
    :type minute: str
    :param hour: Represents the hour component in cron format.
    :type hour: str
    :param day_of_week: Represents the day of the week component in cron format.
    :type day_of_week: str
    :param day_of_month: Represents the day of the month component in cron format.
    :type day_of_month: str
    :param month_of_year: Represents the month component in cron format.
    :type month_of_year: str
    """

    period: str
    minute: str = "*"
    hour: str = "*"
    day_of_week: str = "*"
    day_of_month: str = "*"
    month_of_year: str = "*"


# TODO: Create Base/Write models  # noqa: TD002, TD003
class TaskHistory(BaseSQLModel, table=True):
    """Represent a task execution history.

    :param execution_request: The request that triggered the task execution.
    :type execution_request: TaskExecutionRequest
    :param status: The status of the task execution. Defaults to pending.
    :type status: TaskHistoryStatusEnum
    :param task_id: The ID of the task associated with the execution.
    :type task_id: int
    :param task: The task associated with this execution history.
    :type task: Task
    """

    __table_args__ = (Index("ix_taskhistory_task_id_status", "task_id", "status"),)
    execution_request: TaskExecutionRequest = SQLField(
        sa_column=Column(JSON, nullable=False),
    )
    status: TaskHistoryStatusEnum = SQLField(
        default=TaskHistoryStatusEnum.PENDING,
        sa_column=Column(EnumField(TaskHistoryStatusEnum), nullable=False, index=True),
    )
    task_id: int = SQLField(foreign_key="task.id", index=True)
    task: Task = Relationship(back_populates="history")

    @computed_field
    @property
    def errors(self) -> list:
        """Return a list of errors for the executed task.

        :return: A list of error messages encountered during task execution.
        :rtype: list[str]
        """
        if self.status not in [
            TaskHistoryStatusEnum.SUCCESS,
            TaskHistoryStatusEnum.FAILED,
        ] or not self.execution_request.tracking.get("task_states"):
            return []
        errors = set()
        for state in self.execution_request.tracking["task_states"].values():
            for event in state["Events"]:
                match event["Type"]:
                    case "Driver Failure":
                        errors.add(event["DisplayMessage"])
        return list(errors)


class TaskHistoryResponse(BaseSQLModel):
    """Represent a task history API response.

    :param execution_request: The request that triggered the task execution.
    :type execution_request: TaskExecutionRequest
    :param status: The status of the task execution.
    :type status: TaskHistoryStatusEnum
    :param task: The task associated with this execution history.
    :type task: Task
    :param errors: A list of errors encountered during the task execution.
    :type errors: list[str]
    """

    execution_request: TaskExecutionRequest
    status: TaskHistoryStatusEnum
    task: Task
    errors: list


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
            self._durations["tasks"][task.id] = (
                task.execution_request.tracking[  # TODO: Use Pydantic models  # noqa: TD002, TD003
                    "duration"
                ]
            )
            self._raw["durations"].append(task.execution_request.tracking["duration"])
            self._raw["finished_at"].append(
                task.execution_request.tracking["finished_at"],
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


class TaskLog(BaseModel):
    """Define a task log line.

    :param step: The task step name.
    :type step: str
    :param type: The type of log to stream ('stdout' or 'stderr').
    :type type: Literal["stdout", "stderr"]
    :param msg: The log message. If None, represents the end of the log for that step.
    :type msg: str | None
    """

    step: str
    type: Literal["stdout", "stderr"]
    msg: str | None

"""Define models for the Task API.

Todo:
----
  - ensure that we can handle arbitrary parameters for invocation, which should allow mapping
    to HTML form fields to allow for dynamic rendering when executing a task via the UI
  - owner of a task, allowing app-only, general use, etc (Casdoor potentially)
    e.g. owner = tasks, owner = alters, owner = *
  - scheduled task, which can run at a specific time, or require manual invocation

"""

from datetime import datetime
from enum import auto
from enum import StrEnum
from statistics import mean

from pydantic import AliasGenerator
from pydantic import BaseModel
from pydantic import computed_field
from pydantic import ConfigDict
from pydantic import Field
from sqlalchemy import Column
from sqlalchemy import Enum as EnumField
from sqlalchemy import Index
from sqlalchemy import JSON
from sqlmodel import Field as SQLField
from sqlmodel import Relationship

from app.core.db import BaseSQLModel
from app.core.db.models import DateTimeWithTimezone

TASK_ALIAS_LENGTH = 100


class TaskBackendEnum(StrEnum):
    """Control the choice of backends.

    Attributes
    ----------
    NOMAD : str
        Enum value for Nomad backend.

    """

    NOMAD = auto()


class TaskHistoryStatusEnum(StrEnum):
    """Define status codes for task executions.

    Attributes
    ----------
    FAILED : str
        Enum value for failed tasks.
    PENDING : str
        Enum value for pending tasks.
    RUNNING : str
        Enum value for running tasks.
    SUCCESS : str
        Enum value for successfully completed tasks.

    """

    FAILED = auto()
    PENDING = auto()
    RUNNING = auto()
    SUCCESS = auto()


class TaskExecutionRequest(BaseModel):
    """Represent an execution request.

    Attributes
    ----------
    task : str
        The task name.
    target : str
        The target system or environment.
    meta : dict, optional
        Additional metadata for the task. Defaults to an empty dictionary.
    tracking : dict, optional
        Tracking information for task execution. Defaults to a dictionary with keys
        for allocation and evaluation IDs.

    """

    model_config = ConfigDict(extra="allow")
    task: str
    target: str
    meta: dict | None = {}
    tracking: dict | None = {"allocation_id": None, "evaluation_id": None}


class TaskGroupTaskTemplate(BaseModel):
    """Represent a task group for controlling task templates.

    Attributes
    ----------
    content : str or bytes
        The content of the task template.
    path : str
        The file path where the template will be applied.
    mode : str
        The execution mode of the task. Defaults to "restart".
    perms : str
        The file permissions for the template. Defaults to "0644".

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
    """Represent a task that belong to a job task group.

    Attributes
    ----------
    name : str
        The name of the task.
    driver : str
        The driver to be used for task execution. Defaults to "raw_exec".
    user : str
        The user who will execute the task. Defaults to an empty string.
    config : dict or list or str or bytes
        The configuration details for the task.
    meta : dict
        Additional metadata for the task. Defaults to an empty dictionary.
    restart : dict
        Task restart policy. Defaults to a dictionary specifying no retries.
    templates : list[TaskGroupTaskTemplate]
        A list of task templates to be applied. Defaults to an empty list.

    """

    model_config = ConfigDict(
        alias_generator=AliasGenerator(
            serialization_alias=lambda field_name: field_name.title(),
        ),
    )  # TODO: Reuse
    name: str
    driver: str = "raw_exec"
    user: str = ""
    config: dict | list | str | bytes
    meta: dict = {}  # TODO
    restart: dict = {"attempts": 0, "mode": "fail"}  # TODO
    templates: list[TaskGroupTaskTemplate] = []  # TODO


class TaskGroup(BaseModel):
    """Represent a task group.

    Attributes
    ----------
    engine : str
        The backend engine for task execution. Defaults to "nomad".
    name : str
        The name of the task group. Defaults to "execution".
    parallel : bool
        Whether tasks should be executed in parallel. Defaults to False.
    tasks : list[TaskGroupTask]
        A list of tasks in the group.

    """

    engine: str = "nomad"
    name: str = "execution"
    parallel: bool = False
    tasks: list[TaskGroupTask] = []

    # TODO: Return Pydantic model
    def to_payload(self) -> dict[str, list[dict]]:
        """Convert to a backend-specific payload format.

        Returns
        -------
        dict
            A dictionary representing the payload for the task group.

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

    Attributes
    ----------
    app : str
        The application name associated with the task.
    commands : list
        A list of commands to execute the task.
    name : str
        The task name.
    target : str
        The target system for task execution.
    artifacts : list or None
        Artifacts produced by the task. Defaults to None.
    parallel : bool
        Whether the task will run in parallel. Defaults to False.
    persist : bool
        Whether the task should persist after completion. Defaults to True.
    schedule : dict
        The scheduling configuration for the task. Defaults to {"save_only": True}.
    template : str
        The task template type. Defaults to "batch".

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


# TODO: Create Base/Write/Response models
class Task(BaseSQLModel, table=True):
    """Represent a task stored in the database.

    Attributes
    ----------
    name : str
        The name of the task.
    data : dict
        The task data stored in JSON format.
    backend : TaskBackendEnum
        The backend used for task execution. Defaults to Nomad.
    owner : str or None
        The owner of the task. Defaults to None.
    is_template : bool
        Whether the task is a template. Defaults to False.
    protected : bool
        Whether the task is protected from deletion. Defaults to False.
    history : list[TaskHistory]
        The history of task executions.
    deleted_at : datetime or None
        The deletion timestamp, if applicable.

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
    name: str = SQLField(max_length=255, unique=True, index=True)
    data: dict = SQLField(sa_column=Column(JSON, nullable=False))
    backend: TaskBackendEnum = SQLField(
        default=TaskBackendEnum.NOMAD,
        sa_column=Column(EnumField(TaskBackendEnum), nullable=False),
    )
    owner: str | None = SQLField(default=None, index=True)
    is_template: bool = SQLField(default=False, index=True)
    protected: bool = False
    history: list["TaskHistory"] = Relationship(back_populates="task")
    deleted_at: datetime | None = SQLField(
        sa_type=DateTimeWithTimezone,
        default=None,
        index=True,
    )


# TODO: Create Base/Write models
class TaskHistory(BaseSQLModel, table=True):
    """Represent a task execution history.

    Attributes
    ----------
    execution_request : TaskExecutionRequest
        The request that triggered the task execution.
    status : TaskHistoryStatusEnum
        The status of the task execution. Defaults to pending.
    task_id : int
        The ID of the task associated with the execution.
    task : Task
        The task associated with this execution history.

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

        Returns
        -------
        list
            A list of error messages encountered during task execution.

        """
        if self.status not in [
            TaskHistoryStatusEnum.SUCCESS,
            TaskHistoryStatusEnum.FAILED,
        ] or not self.execution_request.tracking.get("task_states"):
            return []
        errors = set()
        for tasks in self.execution_request.tracking["task_states"].values():
            for state in tasks.values():
                for event in state["Events"]:
                    match event["Type"]:
                        case "Driver Failure":
                            errors.add(event["DisplayMessage"])
        return list(errors)


class TaskHistoryResponse(BaseSQLModel):
    """Represent a task history API response.

    Attributes
    ----------
    execution_request : TaskExecutionRequest
        The request that triggered the task execution.
    status : TaskHistoryStatusEnum
        The status of the task execution.
    task : Task
        The task associated with this execution history.
    errors : list
        A list of errors encountered during the task execution.

    """

    execution_request: TaskExecutionRequest
    status: TaskHistoryStatusEnum
    task: Task
    errors: list


class TaskStats(BaseModel):
    """Model for task statistics.

    Attributes
    ----------
    engine : str
        The backend engine used for task execution. Defaults to "nomad".
    tasks : list[TaskHistory]
        A list of task execution histories.
    total
    status
    duration
    last_finished_at

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

        Returns
        -------
        int
            The total number of tasks.

        """
        return len(self.tasks)

    @computed_field
    @property
    def status(self) -> dict:
        """Return the task status summary.

        Returns
        -------
        dict
            A dictionary summarizing the number of passed and failed tasks.

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

        Returns
        -------
        dict
            A dictionary summarizing average, last, and total task durations.

        """
        if self._durations["average_seconds"] is None:
            self._process()
        return self._durations

    @computed_field
    @property
    def last_finished_at(self) -> str | None:
        """Return the last finished task timestamp.

        Returns
        -------
        str or None
            The timestamp of the last task finished, or None if not available.

        """
        if not self._raw["finished_at"]:
            self._process()
        return max(self._raw["finished_at"]) if self._raw["finished_at"] else None

    def _process(self) -> None:
        """Process the task data."""

        def _durations_from_tracking() -> None:
            self._durations["tasks"][task.id] = (
                task.execution_request.tracking[  # TODO: Use Pydantic models
                    "duration"
                ]
            )
            self._raw["durations"].append(task.execution_request.tracking["duration"])
            self._raw["finished_at"].append(
                task.execution_request.tracking["finished_at"],
            )

        # TODO:
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

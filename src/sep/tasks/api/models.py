"""
Task API data models

TODO:
  - ensure that we can handle arbitrary parameters for invocation, which should allow mapping
    to HTML form fields to allow for dynamic rendering when executing a task via the UI
  - owner of a task, allowing app-only, general use, etc (Casdoor potentially)
    e.g. owner = tasks, owner = alters, owner = *
  - scheduled task, which can run at a specific time, or require manual invocation

"""

from datetime import (
    datetime,
    timedelta,
)
from enum import IntEnum
from statistics import mean
from typing import Optional, Any

from pydantic import (
    BaseModel as PydanticBaseModel,
    computed_field,
    ConfigDict,
    Field,
    model_serializer,
)
from sqlalchemy import (
    BigInteger,
    Column,
    Enum,
    event,
    Index,
    Integer,
    JSON,
    null,
    String,
    Table,
    UniqueConstraint,
)
# from sqlalchemy.ext.declarative import declarative_base

from sep.core.db import (
    DATABASE_EXTRA_COLUMNS,
    DbBaseModel,
    get_metadata,
)

TASK_ALIAS_LENGTH = 100
TASK_BACKEND_MAP = {  # CAUTION: changing existing values should be done with the utmost care
    "nomad": 1,
}
TASK_BACKEND_LOOKUP = {v: k for k, v in TASK_BACKEND_MAP.items()}

TASK_HISTORY_STATUS_MAP = {  # CAUTION: changing existing values should be done with the utmost care
    "failed": 1,
    "pending": 2,
    "running": 3,
    "success": 0,
}
TASK_HISTORY_STATUS_LOOKUP = {v: k for k, v in TASK_HISTORY_STATUS_MAP.items()}

# SchemaBase = declarative_base(metadata=get_metadata())


class BaseModel(PydanticBaseModel):
    """Custom Pydantic base model"""

    engine: str = "nomad"

    _excluded_fields = ["engine"]
    _transform_fields = {"nomad": {"*": "capitalize"}}


class CustomSerializeBaseModel(BaseModel):
    """Extended base model for customisation"""

    def format_attr_name(self, attr: str) -> str:
        """Format an attribute name, such as when dumping the model

        :param attr:
        :return:
        """
        mapping = self._transform_fields.get(self.engine, {})
        if attr in mapping:
            transform = mapping[attr]
        elif "*" in mapping:
            transform = mapping["*"]
        else:
            transform = "__str__"
        return getattr(attr, transform)() if hasattr(attr, transform) else transform

    @model_serializer
    def serialize_model(self) -> Any:
        """Special serializer for models"""
        match self.engine:
            case _:
                return {self.format_attr_name(k): v for k, v in vars(self).items() if k not in self._excluded_fields}


class TaskBackendEnum(IntEnum):
    """
    Control the choice of backends
    """

    nomad = TASK_BACKEND_MAP["nomad"]


class TaskHistoryStatusEnum(IntEnum):
    """
    Status codes
    """

    failed = TASK_HISTORY_STATUS_MAP["failed"]
    pending = TASK_HISTORY_STATUS_MAP["pending"]
    running = TASK_HISTORY_STATUS_MAP["running"]
    success = TASK_HISTORY_STATUS_MAP["success"]


class TaskExecution(BaseModel):
    """Model for initiating task execution"""

    task: str


class TaskExecutionRequest(CustomSerializeBaseModel):
    """Model for execution requests"""

    model_config = ConfigDict(extra="allow")

    task: str
    target: str
    meta: Optional[dict] = {}
    tracking: Optional[dict] = {"allocation_id": None, "evaluation_id": None}

    @model_serializer
    def serialize_model(self) -> Any:
        """Special serializer for models"""
        return {k: v for k, v in vars(self).items() if k not in self._excluded_fields}


class TaskGroupTaskTemplate(CustomSerializeBaseModel):
    """Model for controlling task templates"""

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
        }
    }


class TaskGroupTask(CustomSerializeBaseModel):
    """Model for tasks that belong to a job task group task"""

    name: str
    driver: str = "raw_exec"
    user: str = ""
    config: dict
    meta: dict = {}  # TODO
    restart: dict = {"attempts": 0, "mode": "fail"}  # TODO
    templates: list[TaskGroupTaskTemplate] = []  # TODO


class TaskGroup(CustomSerializeBaseModel):
    """Model for task group tasks"""

    engine: str = "nomad"
    name: str = "execution"
    parallel: bool = False
    tasks: list[TaskGroupTask] = []

    def to_payload(self):
        """Convert to a backend-specific payload format

        :return:
        """
        data = {"TaskGroups": []}
        match self.engine:
            case _:  # Nomad by default and parallelisation is controlled here for now
                if self.parallel:
                    for i, task in enumerate(self.tasks):
                        data["TaskGroups"].append({"Name": f"{self.name}{i+1}", "Tasks": [task.model_dump()]})
                else:
                    data["TaskGroups"].append({"Name": self.name, "Tasks": [task.model_dump() for task in self.tasks]})
        return data


class GeneratedTask(CustomSerializeBaseModel):
    """Model for a generated task"""

    app: str
    commands: list
    name: str
    target: str
    artifacts: list | None = None
    config: str | None = None
    parallel: bool = False
    persist: bool = True
    schedule: dict = {}  # TODO
    template: str = "batch"


class Task(DbBaseModel):
    """
    Model for tasks
    """

    name: str
    data: str

    backend: TaskBackendEnum = TaskBackendEnum.nomad
    meta: dict = {"owners": ["*"]}


class TaskHistory(DbBaseModel):
    """Model for task history"""

    name: str
    execution_request: TaskExecutionRequest
    data: Task
    status: int = TASK_HISTORY_STATUS_MAP["pending"]

    @computed_field
    @property
    def errors(self) -> list:
        """Return a list of errors for the executed task

        :return:
        """
        if (
            self.status not in [TASK_HISTORY_STATUS_MAP["success"], TASK_HISTORY_STATUS_MAP["failed"]]
            or not self.execution_request.tracking["task_states"]
        ):
            return []
        errors = set()
        for _, tasks in self.execution_request.tracking["task_states"].items():
            for _, state in tasks.items():
                for event in state["Events"]:
                    match event["Type"]:
                        case "Driver Failure":
                            errors.add(event["DisplayMessage"])
        return list(errors)


class TaskStats(BaseModel):
    """Model for task stats"""

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
        """The total number of tasks

        :return:
        """
        return len(self.tasks)

    @computed_field
    @property
    def status(self) -> dict:
        """The status summary

        :return:
        """
        status = {
            "pass": 0,
            "fail": 0,
        }
        for task in self.tasks:
            match TASK_HISTORY_STATUS_LOOKUP[task.status]:
                case "failed":
                    status["fail"] += 1
                case "success":
                    status["pass"] += 1
                case _:
                    pass
        return status

    @computed_field
    @property
    def duration(self) -> dict:
        """The duration summary

        :return:
        """
        if self._durations["average_seconds"] is None:
            self._process()
        return self._durations

    @computed_field
    @property
    def last_finished_at(self) -> str | None:
        """Find the last datetime that the task finished running

        :return:
        """
        if not self._raw["finished_at"]:
            self._process()
        return max(self._raw["finished_at"]) if self._raw["finished_at"] else None

    def _process(self):
        """Process the task data

        :return:
        """

        # def _durations_from_states():
        #    for _, state in task.execution_request.tracking["task_states"].items():
        #        for _, info in state.items():
        #            _f = datetime.fromisoformat(info["FinishedAt"])
        #            _s = datetime.fromisoformat(info["StartedAt"] if info["StartedAt"] else info["FinishedAt"])
        #            self._durations["tasks"][task.id] = (_f - _s).seconds
        #            self._raw["durations"].append(self._durations["tasks"][task.id])
        #            self._raw["finished_at"].append(str(_f))

        def _durations_from_tracking():
            self._durations["tasks"][task.id] = task.execution_request.tracking["duration"]
            self._raw["durations"].append(task.execution_request.tracking["duration"])
            self._raw["finished_at"].append(task.execution_request.tracking["finished_at"])

        # TODO:
        #  - handle extra backends
        #  - consider moving some logic to the TaskHistory model and then call from here
        for i, task in enumerate(self.tasks):
            if i == 0:
                self.engine = TASK_BACKEND_LOOKUP[task.data.backend]
            try:
                _durations_from_tracking()
            except KeyError:
                return None
        if self._raw["durations"]:
            self._durations.update(
                average_seconds=mean(self._raw["durations"]),
                last_seconds=self._raw["durations"].pop(),
                total_seconds=sum(self._raw["durations"]),
            )


# class Tasks(SchemaBase):
#    """Schema definition for Task"""
#
#    __tablename__ = "tasks"
#
#    id = Column(
#        BigInteger().with_variant(Integer, dialect_name="sqlite"),
#        autoincrement=True,
#        nullable=False,
#        primary_key=True,
#    )
#    name = Column(String(TASK_ALIAS_LENGTH), nullable=False)
#    data = Column(JSON, nullable=False)
#    backend = Column(Enum(TaskBackendEnum).with_variant(Integer, dialect_name="sqlite"), default=null(), nullable=True)
#    meta = Column(JSON, nullable=False)
#
#
# class TasksHistory(SchemaBase):
#    """Schema definition for TaskHistory"""
#    __tablename__ = "tasks_history"
#
#    id = Column(
#        BigInteger().with_variant(Integer, dialect_name="sqlite"),
#        autoincrement=True,
#        nullable=False,
#        primary_key=True,
#    )
#    name = Column(String(TASK_ALIAS_LENGTH), nullable=False)
#    execution_request = Column(JSON, nullable=False)
#    data = Column(JSON, nullable=False)
#    status = Column(Enum(TaskHistoryStatusEnum).with_variant(Integer, dialect_name="sqlite"), nullable=False)


# @event.listens_for(Tasks, "engine_connect")
# def init_data(table: Table, connection, **kw):
#    """Initialize/update the data when connecting to the engine
#
#    :param table:
#    :param connection:
#    :param kw:
#    :return:
#    """
#    match table.name:
#        case "tasks":
#            query = table.select().where(table.c.name == "generic-nomad")
#    # connection.execute(table.insert(), )


tasks = Table(
    "tasks",
    get_metadata(),
    Column(
        "id",
        BigInteger().with_variant(Integer, dialect_name="sqlite"),
        autoincrement=True,
        nullable=False,
        primary_key=True,
    ),
    Column("name", String(TASK_ALIAS_LENGTH), nullable=False),
    Column("data", JSON, nullable=False),
    Column(
        "backend", Enum(TaskBackendEnum).with_variant(Integer, dialect_name="sqlite"), default=null(), nullable=True
    ),
    Column("meta", JSON, nullable=False),
)
# tasks = Tasks()

history = Table(
    "tasks_history",
    get_metadata(),
    Column(
        "id",
        BigInteger().with_variant(Integer, dialect_name="sqlite"),
        autoincrement=True,
        nullable=False,
        primary_key=True,
    ),
    Column("name", String(TASK_ALIAS_LENGTH), nullable=False),
    Column("execution_request", JSON, nullable=False),
    Column("data", JSON, nullable=False),
    Column("status", Enum(TaskHistoryStatusEnum).with_variant(Integer, dialect_name="sqlite"), nullable=False),
)
# history = TasksHistory()

# UniqueConstraint("name", tasks.name)
Index("task_name", history.name)

for col in DATABASE_EXTRA_COLUMNS:
    tasks.append_column(col.copy())
    history.append_column(col.copy())

(UniqueConstraint("name", "deleted_at"),)

"""Define models for the Tasks plugin."""

from typing import Literal

from pydantic import BaseModel

from app.core.fields import RequiredStr
from app.tasks.models import TaskBackendEnum


class TaskCreateRequest(BaseModel):
    """Create a new task with the specified parameters.

    :param name: The unique name of the task.
    :type name: RequiredStr
    :param payload: The payload for the task.
    :type payload: RequiredStr
    :param fmt: The format of the payload. Supported formats are "hcl", "json", and
        "yaml".
    :type fmt: Literal["hcl", "json", "yaml"]
    :param backend: The backend system to use for task execution.
    :type backend: TaskBackendEnum
    :param owner: The owner of the task.
    """

    name: RequiredStr
    payload: RequiredStr  # TODO: Validate trying to parse
    fmt: Literal["hcl", "json", "yaml"]
    backend: TaskBackendEnum
    owner: RequiredStr

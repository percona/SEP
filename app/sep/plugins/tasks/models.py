"""Define models for the Tasks plugin."""

from typing import Literal

from pydantic import BaseModel

from app.core.utils.fields import RequiredStr
from app.tasks.models import TaskBackendEnum, TaskOwner


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
    :type owner: TaskOwner
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    name: RequiredStr
    payload: RequiredStr  # TODO: Validate trying to parse  # noqa: TD002, TD003
    fmt: Literal["hcl", "json", "yaml"]
    backend: TaskBackendEnum
    owner: TaskOwner
    alert_on_fail: bool = False

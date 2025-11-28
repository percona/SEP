"""Define models for the Dipper plugin."""

from pydantic import BaseModel

from app.core.utils.fields import RequiredStr


class FormCreate(BaseModel):
    """Represent a Dipper creation form.

    :param task_name: The name of the task to be created.
    :type task_name: RequiredStr
    :param hostname: The target hostname for the task execution.
    :type hostname: RequiredStr
    :param alert_on_fail: If True, send an alert if the task fails. Defaults to False.
    :type alert_on_fail: bool
    """

    task_name: RequiredStr
    hostname: RequiredStr
    alert_on_fail: bool = False

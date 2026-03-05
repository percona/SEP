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

"""Define models for the Tasks plugin."""

from typing import Literal

from pydantic import BaseModel

from app.core.utils.fields import NonEmptyStr
from app.tasks.models import TaskBackendEnum, TaskOwner


class TaskCreateRequest(BaseModel):
    """Create a new task with the specified parameters.

    :param name: The unique name of the task.
    :type name: NonEmptyStr
    :param payload: The payload for the task.
    :type payload: NonEmptyStr
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

    name: NonEmptyStr
    payload: NonEmptyStr  # TODO: Validate trying to parse  # noqa: TD002, TD003
    fmt: Literal["hcl", "json", "yaml"]
    backend: TaskBackendEnum
    owner: TaskOwner
    alert_on_fail: bool = False

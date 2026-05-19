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

"""Define models for the Gascan plugin."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.core.utils.fields import NonEmptyStr
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskOwner


class GascanCreate(BaseModel):
    """Represent a Gascan creation form.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param playbook: The playbook to run.
    :type playbook: NonEmptyStr
    :param limit: Optional limit expression for the playbook run.
    :type limit: str
    :param override: Optional override values for the playbook run.
    :type override: str
    :param alert_on_fail: If True, send an alert if the task fails.
    :type alert_on_fail: bool
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    playbook: NonEmptyStr
    limit: str = ""
    override: str = ""
    alert_on_fail: bool = False


class GascanTaskWrite(BaseModel):
    """Represent a JSON request body for creating a gascan task.

    :param task_name: The name of the task to be created.
    :type task_name: NonEmptyStr
    :param hostname: The target hostname for the task execution.
    :type hostname: NonEmptyStr
    :param playbook: The playbook to run.
    :type playbook: NonEmptyStr
    :param limit: Optional limit expression for the playbook run.
    :type limit: str
    :param override: Optional override values for the playbook run.
    :type override: str
    :param alert_on_fail: If True, send an alert if the task fails.
    :type alert_on_fail: bool
    """

    task_name: NonEmptyStr
    hostname: NonEmptyStr
    playbook: NonEmptyStr
    limit: str = ""
    override: str = ""
    alert_on_fail: bool = False


class GascanTaskBase(BaseModel):
    """Define the common fields shared across gascan task API responses.

    :param name: The name of the gascan task.
    :type name: str
    :param owner: The entity or user that owns the task.
    :type owner: TaskOwner
    :param status: The current execution status of the task.
    :type status: TaskHistoryStatusEnum | None
    """

    name: str
    owner: TaskOwner
    status: TaskHistoryStatusEnum | None = None


class GascanTaskResponse(GascanTaskBase):
    """Represent a gascan task API response.

    :param id: The unique identifier for the gascan task.
    :type id: int | None
    :param backend: The backend worker/engine executing the task.
    :type backend: TaskBackendEnum
    :param data: The raw configuration and parameters used for execution.
    :type data: dict[str, Any]
    :param protected: Whether the task is protected from deletion or modification.
    :type protected: bool
    :param alert_on_fail: If True, notifications are sent upon task failure.
    :type alert_on_fail: bool
    :param created_at: The timestamp when the task was first created.
    :type created_at: datetime | None
    :param updated_at: The timestamp of the last modification to the task record.
    :type updated_at: datetime | None
    :param created_by: The user who initiated the task.
    :type created_by: str | None
    :param last_updated_by: The user who last modified the task record.
    :type last_updated_by: str | None
    """

    id: int | None = None
    backend: TaskBackendEnum
    data: dict[str, Any]
    protected: bool
    alert_on_fail: bool
    created_at: datetime | None = None
    updated_at: datetime | None = None
    created_by: str | None = None
    last_updated_by: str | None = None

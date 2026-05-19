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

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

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


class TaskListResponse(BaseModel):
    """Represent one task row in the read-only tasks plugin list API.

    :param name: The unique name of the task.
    :type name: str
    :param backend: The backend system used for task execution.
    :type backend: TaskBackendEnum
    :param created_at: When the task was created, or ``None`` if unavailable.
    :type created_at: str | None
    :param created_by: The user ID of the user who created the task, or
        ``None`` if unknown.
    :type created_by: str | None
    :param last_updated_by: The user ID of the user who last updated the
        task, or ``None`` if unknown.
    :type last_updated_by: str | None
    """

    name: str
    backend: TaskBackendEnum
    created_at: str | None = None
    created_by: str | None = None
    last_updated_by: str | None = None


class ExecutorHostMetadata(BaseModel):
    """Represent one executor host option for display on the task detail page.

    :param value: The executor host value submitted with task execution
        requests (Nomad node name).
    :type value: str
    :param label: The human-readable label for the host (often an inventory
        display name).
    :type label: str
    """

    value: str
    label: str


class PeriodicTaskSummary(BaseModel):
    """Represent read-only periodic-schedule metadata for a single task.

    :param id: The periodic task's database identifier.
    :type id: int
    :param name: The periodic task's display name.
    :type name: str
    :param enabled: Whether the periodic schedule is currently enabled.
    :type enabled: bool
    :param period: A human-readable schedule description (cron or interval),
        or ``None`` when unavailable.
    :type period: str | None
    :param next_run_at: The next scheduled run time in ISO 8601 format, or
        ``None`` when not scheduled.
    :type next_run_at: str | None
    :param last_run_at: The last run time in ISO 8601 format, or ``None`` if
        the schedule has never run.
    :type last_run_at: str | None
    :param total_run_count: The total number of times the schedule has run,
        or ``None`` when unavailable.
    :type total_run_count: int | None
    :param chain_task_names: Ordered task names in the periodic execution
        chain, if any.
    :type chain_task_names: list[str]
    """

    id: int
    name: str
    enabled: bool
    period: str | None = None
    next_run_at: str | None = None
    last_run_at: str | None = None
    total_run_count: int | None = None
    chain_task_names: list[str] = Field(default_factory=list)


class TaskDetailResponse(BaseModel):
    """Represent the aggregate payload for ``GET /api/plugins/tasks/{task_name}``.

    Bundles the task definition, running executions, execution history,
    periodic schedules, and executor host metadata into a single response for
    the React detail page.

    :param task: The task definition as returned by the tasks API.
    :type task: dict[str, Any]
    :param running_tasks: Task history rows with status ``RUNNING``.
    :type running_tasks: list[dict[str, Any]]
    :param execution_history: Paginated task history from the tasks API
        (``items``, ``total``, ``offset``, ``limit``).
    :type execution_history: dict[str, Any]
    :param periodic_summary: Read-only summaries of periodic schedules
        attached to this task.
    :type periodic_summary: list[PeriodicTaskSummary]
    :param executor_hosts: Executor hosts available for display, with
        inventory-resolved labels when possible.
    :type executor_hosts: list[ExecutorHostMetadata]
    """

    model_config = ConfigDict(extra="forbid")

    task: dict[str, Any]
    running_tasks: list[dict[str, Any]] = Field(default_factory=list)
    execution_history: dict[str, Any] = Field(default_factory=lambda: {"items": []})
    periodic_summary: list[PeriodicTaskSummary] = Field(default_factory=list)
    executor_hosts: list[ExecutorHostMetadata] = Field(default_factory=list)

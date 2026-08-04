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

from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.core.utils.fields import ARBITRARY_ARGS_SCHEMA, UTCDatetime
from app.tasks.models import TaskBackendEnum, TaskHistoryStatusEnum, TaskResponse


class TaskListResponse(BaseModel):
    """Represent one task row in the read-only tasks plugin list API.

    :param name: The unique name of the task.
    :type name: str
    :param backend: The backend system used for task execution.
    :type backend: TaskBackendEnum
    :param created_at: When the task was created, or ``None`` if unavailable.
    :type created_at: UTCDatetime | None
    :param created_by: Display name for the task creator (Casdoor username when
        resolvable, otherwise the stored user id), or ``None`` if unknown.
    :type created_by: str | None
    :param last_updated_by: Display name for the user who last updated the
        task (Casdoor username when resolvable, otherwise the stored user id),
        or ``None`` if unknown.
    :type last_updated_by: str | None
    """

    name: str
    backend: TaskBackendEnum
    created_at: UTCDatetime | None = None
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
    :type next_run_at: UTCDatetime | None
    :param last_run_at: The last run time in ISO 8601 format, or ``None`` if
        the schedule has never run.
    :type last_run_at: UTCDatetime | None
    :param total_run_count: The total number of times the schedule has run,
        or ``None`` when unavailable.
    :type total_run_count: int | None
    :param last_run_status: The result of this schedule's own most recent run,
        or ``None`` when the schedule has never run.
    :param chain_task_names: Ordered task names in the periodic execution
        chain, if any.
    :type chain_task_names: list[str]
    """

    id: int
    name: str
    enabled: bool
    period: str | None = None
    next_run_at: UTCDatetime | None = None
    last_run_at: UTCDatetime | None = None
    total_run_count: int | None = None
    last_run_status: TaskHistoryStatusEnum | None = None
    chain_task_names: list[str] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def populate_chain_task_names(cls, data: Any) -> Any:
        """Populate ``chain_task_names`` from ``execute_request`` before validation.

        :param data: The raw periodic-task payload from the tasks API.
        :type data: Any
        :return: The payload with ``chain_task_names`` normalized for validation.
        :rtype: Any
        """
        if not isinstance(data, dict):
            return data
        normalized = dict(data)
        execute_request = normalized.get("execute_request") or {}
        normalized["chain_task_names"] = execute_request.get("chain_task_names") or []
        return normalized


class TaskDetailResponse(BaseModel):
    """Represent the aggregate payload for ``GET /api/apps/tasks/{task_name}``.

    Bundle the task definition, execution history, periodic schedules, and
    executor host metadata into a single response for the React detail page.

    :param task: The task definition as returned by the tasks API.
    :type task: TaskResponse
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

    task: TaskResponse
    execution_history: dict[str, Any] = Field(
        default_factory=lambda: {"items": [], "total": 0, "offset": 0, "limit": 0},
        json_schema_extra=ARBITRARY_ARGS_SCHEMA,
    )
    periodic_summary: list[PeriodicTaskSummary] = Field(default_factory=list)
    executor_hosts: list[ExecutorHostMetadata] = Field(default_factory=list)

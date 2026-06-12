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

"""Provide the shared JSON-API list pipeline and default task response builder."""

from collections.abc import Callable, Mapping, Sequence
from typing import Any, overload, Protocol, TypeVar

from pydantic import BaseModel

from app.core.pagination import PaginatedResponse, Pagination
from app.sep.deps import TaskAPI
from app.sep.plugins.framework.task_status import batch_get_latest_statuses
from app.tasks.models import Task, TaskHistoryStatusEnum

R = TypeVar("R", bound=BaseModel)


class TaskResponseBuilder(Protocol[R]):
    """Build a JSON-API response model from a task and its latest status.

    The list pipeline always invokes the builder as
    ``response_builder(task, status=...)``, so every per-plugin builder whose
    ``status`` is positional-or-keyword or keyword-only is a structural subtype.
    """

    def __call__(self, task: Task, *, status: TaskHistoryStatusEnum | None = None) -> R:
        """Build the response model for ``task`` and its latest ``status``."""


def build_default_task_response(
    response_model: type[R],
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
    *,
    extras: Mapping[str, Any] | None = None,
) -> R:
    """Build ``response_model`` from a task dump plus status and optional extras.

    ``extras`` is merged over the dumped payload with ``dict.update`` semantics,
    so it can both add new fields (``service_type``, ``hostname``,
    ``backup_type``, ``connectivity_warning``) and override dumped ones (the
    ``created_by`` / ``last_updated_by`` username remap, or a mutated ``data``
    carrying ``_command_line``).

    :param response_model: The response model class to construct.
    :type response_model: type[R]
    :param task: The task to dump into the response payload.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :param extras: Fields merged over the dumped payload (add or override).
    :type extras: Mapping[str, Any] | None
    :return: A validated response model instance.
    :rtype: R
    """
    payload = task.model_dump()
    payload["status"] = status
    if extras:
        payload.update(extras)
    return response_model(**payload)


def _owner_list_params(owner: str, pagination: Pagination | None) -> dict[str, Any]:
    """Build the upstream task-list GET params for ``owner`` and a page window."""
    params = {"owner": owner}
    if pagination is not None:
        params |= pagination.model_dump()
    return params


async def _enrich_statuses(
    tasks_api: TaskAPI, tasks: Sequence[Task]
) -> dict[str, TaskHistoryStatusEnum | None]:
    """Resolve each task's latest history status as a discrete pipeline step.

    Isolated as its own step rather than inlined into the assembly so the
    pipeline's enrichment phase stays composable with sibling enrichment steps.

    :param tasks_api: The Tasks API client used for the batch lookup.
    :type tasks_api: TaskAPI
    :param tasks: The tasks to resolve latest statuses for.
    :type tasks: Sequence[Task]
    :return: A mapping from each task name to its latest status or ``None``.
    :rtype: dict[str, TaskHistoryStatusEnum | None]
    """
    return await batch_get_latest_statuses(tasks_api, [task.name for task in tasks])


@overload
async def build_task_list_responses(
    tasks_api: TaskAPI,
    *,
    owner: str,
    response_builder: TaskResponseBuilder[R],
    pagination: None = None,
    status_filter: TaskHistoryStatusEnum | None = None,
    task_filter: Callable[[Task], bool] | None = None,
) -> list[R]: ...


@overload
async def build_task_list_responses(
    tasks_api: TaskAPI,
    *,
    owner: str,
    response_builder: TaskResponseBuilder[R],
    pagination: Pagination,
    status_filter: TaskHistoryStatusEnum | None = None,
    task_filter: Callable[[Task], bool] | None = None,
) -> PaginatedResponse[R]: ...


async def build_task_list_responses(
    tasks_api: TaskAPI,
    *,
    owner: str,
    response_builder: TaskResponseBuilder[R],
    pagination: Pagination | None = None,
    status_filter: TaskHistoryStatusEnum | None = None,
    task_filter: Callable[[Task], bool] | None = None,
) -> list[R] | PaginatedResponse[R]:
    """Assemble JSON-API task responses for an owner through one shared pipeline.

    The pipeline fetches the owner's tasks, applies an optional ``task_filter``
    before any status fan-out, enriches each surviving task with its latest
    status, selects the ones matching ``status_filter``, and builds a response
    per selection. Unpaginated calls return a ``list``; supplying ``pagination``
    returns a ``PaginatedResponse`` whose ``total`` is the filtered current-page
    count when a client-side filter (``status_filter`` or ``task_filter``) is
    active and the upstream total otherwise.

    :param tasks_api: The Tasks API client used for the list and status lookups.
    :type tasks_api: TaskAPI
    :param owner: The task owner to list tasks for.
    :type owner: str
    :param response_builder: Builder invoked as ``builder(task, status=...)``.
    :type response_builder: TaskResponseBuilder[R]
    :param pagination: Page window; when omitted a plain ``list`` is returned.
    :type pagination: Pagination | None
    :param status_filter: Keep only tasks whose latest status matches this.
    :type status_filter: TaskHistoryStatusEnum | None
    :param task_filter: Predicate applied before status enrichment.
    :type task_filter: Callable[[Task], bool] | None
    :return: The built responses, paginated when ``pagination`` is supplied.
    :rtype: list[R] | PaginatedResponse[R]
    """
    response = await tasks_api.get("/", params=_owner_list_params(owner, pagination))
    tasks = [Task.model_validate(item) for item in response["items"]]
    if task_filter is not None:
        tasks = [task for task in tasks if task_filter(task)]

    statuses = await _enrich_statuses(tasks_api, tasks)

    selected = [
        task
        for task in tasks
        if status_filter is None or statuses.get(task.name) == status_filter
    ]
    items = [
        response_builder(task, status=statuses.get(task.name)) for task in selected
    ]

    if pagination is None:
        return items
    client_side_filtered = status_filter is not None or task_filter is not None
    total = len(items) if client_side_filtered else response.get("total", len(items))
    return PaginatedResponse.from_pagination(items, total, pagination)

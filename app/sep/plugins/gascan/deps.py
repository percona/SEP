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

"""Define dependencies for the Gascan plugin."""

import logging
import shlex
from collections.abc import Iterable
from typing import Annotated, Any

from fastapi import Depends, Form

from app.sep.deps import (
    DefaultContext,
    ExecutorHostsCtx,
    get_task_by_name,
    get_tasks_context,
    InventoryAPI,
    TaskAPI,
)
from app.sep.plugins.gascan.models import GascanCreate, GascanTaskResponse, GascanTaskWrite
from app.tasks.models import (
    Task,
    TaskBackendEnum,
    TaskHistoryStatusEnum,
    TaskOwner,
    TaskWrite,
)

logger = logging.getLogger(__name__)


def _assemble_gascan_payload(
    *,
    task_name: str,
    hostname: str,
    playbook: str = "",
    limit: str = "",
    override: str = "",
    alert_on_fail: bool = False,
) -> TaskWrite:
    """Build a TaskWrite payload for a gascan run-command job.

    :param task_name: The name of the task.
    :type task_name: str
    :param hostname: The executor host where gascan runs.
    :type hostname: str
    :param playbook: The playbook to run.
    :type playbook: str
    :param limit: Optional limit expression.
    :type limit: str
    :param override: Optional override values.
    :type override: str
    :param alert_on_fail: Whether to alert on task failure.
    :type alert_on_fail: bool
    :return: A fully constructed TaskWrite for the Tasks API.
    :rtype: TaskWrite
    """
    args: list[str] = []
    if playbook:
        args.append(f"--playbook={playbook}")
    if limit:
        args.append(f"--limit={limit}")
    if override:
        args.append(f"--override={override}")

    return TaskWrite(
        owner=TaskOwner.GASCAN,
        backend=TaskBackendEnum.PROXY,
        data={
            "task": "run-command",
            "meta": {
                "command": "gascan",
                "args": shlex.join(args),
                "target": hostname,
            },
        },
        name=task_name,
        target=hostname,
        alert_on_fail=alert_on_fail,
    )


async def build_gascan_task_payload(
    form: Annotated[GascanCreate, Form()],
) -> TaskWrite:
    """Build the gascan task payload from an HTML form submission.

    :param form: The form data for Gascan task creation.
    :type form: GascanCreate
    :return: A fully constructed TaskWrite object.
    :rtype: TaskWrite
    """
    return _assemble_gascan_payload(
        task_name=form.task_name,
        hostname=form.hostname,
        playbook=form.playbook,
        limit=form.limit,
        override=form.override,
        alert_on_fail=form.alert_on_fail,
    )


GascanGeneratedTask = Annotated[TaskWrite, Depends(build_gascan_task_payload)]


def build_gascan_task(body: GascanTaskWrite) -> TaskWrite:
    """Build the gascan task payload from a JSON request body.

    :param body: The validated JSON request body.
    :type body: GascanTaskWrite
    :return: A fully constructed TaskWrite object.
    :rtype: TaskWrite
    """
    return _assemble_gascan_payload(
        task_name=body.task_name,
        hostname=body.hostname,
        playbook=body.playbook,
        limit=body.limit,
        override=body.override,
        alert_on_fail=body.alert_on_fail,
    )


async def get_gascan_task(
    task_name: str,
    tasks_api: TaskAPI,
) -> Task:
    """Fetch and validate a task for the Gascan plugin.

    :param task_name: The name of the task to retrieve.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to query the task service.
    :type tasks_api: TaskAPI
    :return: The retrieved task.
    :rtype: Task
    :raises HTTPNotFoundException: If the task is not found or not owned by Gascan.
    """
    return await get_task_by_name(tasks_api, task_name, TaskOwner.GASCAN)


GascanTask = Annotated[Task, Depends(get_gascan_task)]


def _extract_latest_task_status(
    histories: Iterable[dict[str, Any]],
) -> TaskHistoryStatusEnum | None:
    """Return the latest known status from a task history payload."""
    for history in histories:
        if (status := history.get("status")) is not None:
            return TaskHistoryStatusEnum(status)
    return None


async def get_gascan_task_status(
    task_name: str,
    tasks_api: TaskAPI,
) -> TaskHistoryStatusEnum | None:
    """Fetch the latest execution status for a gascan task.

    :param task_name: The name of the gascan task.
    :type task_name: str
    :param tasks_api: The TaskAPI instance used to query task history.
    :type tasks_api: TaskAPI
    :return: The latest known task status, or ``None`` if no history exists.
    :rtype: TaskHistoryStatusEnum | None
    """
    response = await tasks_api.get(f"/{task_name}/history/")
    return _extract_latest_task_status(response["items"])


def build_gascan_api_task_response(
    task: Task,
    status: TaskHistoryStatusEnum | None = None,
) -> GascanTaskResponse:
    """Build a gascan task response object for the JSON API.

    :param task: The gascan task retrieved from the Tasks API.
    :type task: Task
    :param status: The latest known execution status for the task.
    :type status: TaskHistoryStatusEnum | None
    :return: A validated gascan task API response object.
    :rtype: GascanTaskResponse
    """
    return GascanTaskResponse(
        **task.model_dump(),
        status=status,
    )


async def get_gascan_api_task_responses(
    tasks_api: TaskAPI,
    status: TaskHistoryStatusEnum | None = None,
) -> list[GascanTaskResponse]:
    """Retrieve gascan task responses for the JSON API.

    :param tasks_api: The TaskAPI instance used to query gascan tasks.
    :type tasks_api: TaskAPI
    :param status: Optional latest-history status filter.
    :type status: TaskHistoryStatusEnum | None
    :return: The gascan task responses matching the requested filters.
    :rtype: list[GascanTaskResponse]
    """
    params = {"owner": TaskOwner.GASCAN.value}
    response = await tasks_api.get("/", params=params)
    tasks = [Task.model_validate(task) for task in response["items"]]
    task_status_pairs = [
        (task, await get_gascan_task_status(task.name, tasks_api)) for task in tasks
    ]

    return [
        build_gascan_api_task_response(task, status=task_status)
        for task, task_status in task_status_pairs
        if status is None or task_status == status
    ]


def get_gascan_task_info(task: dict[str, Any]) -> dict[str, Any]:
    """Extract relevant information from a task for the Gascan plugin.

    :param task: The task data retrieved from the Tasks API.
    :type task: dict[str, Any]
    :return: A dictionary containing hostname and playbook information.
    :rtype: dict[str, Any]
    """
    data = task["data"]
    meta = data["meta"]
    form_values = parse_gascan_task_args(meta)
    return {
        "hostname": meta["target"],
        "playbook": form_values.get("playbook", ""),
        "created_by": task.get("created_by"),
        "last_updated_by": task.get("last_updated_by"),
    }


def parse_single_gascan_arg(arg: str, form_values: dict[str, Any]) -> None:
    """Parse a single gascan argument and update form values.

    :param arg: The argument to parse.
    :type arg: str
    :param form_values: The form values dictionary to update.
    :type form_values: dict[str, Any]
    """
    arg_mappings = {
        "--playbook=": "playbook",
        "--limit=": "limit",
        "--override=": "override",
    }

    for arg_pattern, field_name in arg_mappings.items():
        if arg.startswith(arg_pattern):
            form_values[field_name] = arg.split("=", 1)[1]
            return


def parse_gascan_task_args(meta: dict[str, Any]) -> dict[str, Any]:
    """Parse existing task arguments back into form field values.

    :param meta: The task meta containing the args string.
    :type meta: dict[str, Any]
    :return: A dictionary containing form field values.
    :rtype: dict[str, Any]
    """
    form_values = {
        "playbook": "",
        "limit": "",
        "override": "",
    }

    args_string = meta.get("args", "")
    for arg in shlex.split(args_string):
        parse_single_gascan_arg(arg, form_values)

    return form_values


async def get_gascan_index_context(
    inventory_api: InventoryAPI,
    tasks_api: TaskAPI,
    context: DefaultContext,
    executor_hosts_ctx: ExecutorHostsCtx,
) -> dict[str, Any]:
    """Assemble the context for the Gascan plugin index view.

    :param inventory_api: The Inventory API client (unused for service lookup).
    :type inventory_api: InventoryAPI
    :param tasks_api: The TaskAPI client for fetching task data.
    :type tasks_api: TaskAPI
    :param context: The default context to be updated.
    :type context: DefaultContext
    :param executor_hosts_ctx: The executor hosts context for gascan tasks.
    :type executor_hosts_ctx: ExecutorHostsCtx
    :return: An updated context dictionary containing gascan-related data.
    :rtype: dict[str, Any]
    """
    return await get_tasks_context(
        inventory_api,
        tasks_api,
        get_gascan_task_info,
        executor_hosts_ctx,
        context,
        TaskOwner.GASCAN,
        alert_on_fail_default=True,
    )
